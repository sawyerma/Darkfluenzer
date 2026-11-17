"""Workflow-Registry und Medienbibliothek (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from ..media import gallery, models, pipeline
from ..nodes import comfy
from ..v1 import (
    character_pb2,
    comfy_pb2,
    commands_pb2,
)
from ..v1 import stream_pb2 as spb
from .base import _Call, log


class RegistryMixin:
    """Workflow-Registry und Medienbibliothek; Teil von ``Cockpit``."""

    def _install_editor_copies(self) -> None:
        """Editor-Kopien für "Öffnen" in der jeweils ausführenden, eingerichteten Instanz."""
        for key, wf in self.manifest.workflows.items():
            if self._lane_of(wf) is not None:
                comfy.install_editor_copy(self.cfg, self.manifest, key)

    def _fingerprint(self) -> str:
        """Hash über Manifest, lokale Registry und alle registrierten UI-/API-Graphen
        (Registry-Version)."""
        digest = hashlib.sha256(self._manifest_path().read_bytes())
        local = self.cfg.root / models.LOCAL_REGISTRY
        digest.update(local.read_bytes() if local.is_file() else b"")
        for key in sorted(self.manifest.workflows):
            wf = self.manifest.workflows[key]
            for rel in (wf.ui, wf.api):
                digest.update((self.manifest.root / "workflows" / rel).read_bytes())
        return digest.hexdigest()

    def _manifest_path(self) -> Path:
        return self.cfg.root / models.MANIFEST_RELATIVE

    def _registry_mtime(self) -> tuple[int, int]:
        """Änderungsstand von Manifest und lokaler Registry (``local/registry.toml``)."""
        local = self.cfg.root / models.LOCAL_REGISTRY
        return (
            self._manifest_path().stat().st_mtime_ns,
            local.stat().st_mtime_ns if local.is_file() else 0,
        )

    def _reload_if_changed(self) -> str | None:
        """Externe Änderungen an manifest.toml oder local/registry.toml (CLI, git) übernehmen;
        ungültige Fassung -> alte Registry bleibt aktiv, Fehler im Log. Liefert den neuen
        Registry-Hash oder None."""
        mtime = self._registry_mtime()
        if mtime == self._manifest_mtime:
            return None
        self._manifest_mtime = mtime
        try:
            self.manifest = models.load_manifest(self.cfg.root)
        except models.ManifestError as exc:
            log.error("Geänderte Registry ungültig, bisherige bleibt aktiv: %s", exc)
            return None
        self._install_editor_copies()
        log.info("Registry neu geladen (%d Workflows)", len(self.manifest.workflows))
        return self._fingerprint()

    def _workflows(self) -> bytes:
        engines = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"]
        msg = comfy_pb2.Workflows(version=self._registry_version)
        for key, wf in self.manifest.workflows.items():
            eng, ready = self.manifest.engines[wf.engine], engines[wf.engine]
            lane = self._lane_of(wf)
            registry_ui = self.manifest.root / "workflows" / wf.ui
            editor = lane.node.editor_file(key) if lane else None
            info = msg.workflows.add(
                key=key,
                engine=wf.engine,
                engine_title=eng.title,
                kind=eng.kind,
                status=wf.status,
                models_ready=ready["ready"],
                missing_gb=ready["missing_gb"],
                usage=eng.usage,
                title=wf.title,
                enabled=wf.enabled,
                editor_changed=editor is not None
                and editor.is_file()
                and editor.read_bytes() != registry_ui.read_bytes(),
                instance=eng.instance,
                training=wf.training,
                role=eng.role,
                content=wf.content,
                lora_slot=wf.lora is not None,
                uses_character=wf.training or bool(wf.identity),
            )
            if wf.lora is not None:  # ladbare Charakter-LoRAs (SP3 Schritt 4/5)
                names = models.engine_model_names(
                    self.manifest.files, self.manifest.engines, self.manifest.loras, wf.engine
                )
                info.loras.extend(
                    k for k, lo in sorted(self.manifest.loras.items()) if lo.comfy_name in names
                )
            if {"width", "height"} <= set(wf.params):
                for name, (width, height) in eng.formats.items():
                    info.formats.add(name=name, width=width, height=height)
            graph = comfy.load_graph(self.manifest, wf)
            if wf.video and wf.video.mode == "seconds":  # ein Lauf bis zur Engine-Grenze (LTX)
                v = wf.video
                top = min(self.cfg.production.video_max_s, v.seconds_max)
                info.params.add(
                    name="duration_s", type="int", min=1, max=top, label="Gesamtlänge (s)",
                    expert=False, number=float(graph[v.length_node]["inputs"][v.length_input]),
                )  # fmt: skip
            elif wf.video:  # Länge in Sekunden: Gesamtlänge und Abschnittslänge (VideoSettings)
                v = wf.video
                fps_p = wf.params[v.fps]
                fps = float(graph[fps_p.node]["inputs"][fps_p.input])
                frames = int(graph[v.length_node]["inputs"][v.length_input])
                segment = (v.segment_frames_max - 1) / fps
                for name, label, high, value, expert in (
                    ("duration_s", "Gesamtlänge (s)", self.cfg.production.video_max_s,
                     (frames - 1) / fps, False),
                    ("segment_s", f"Abschnittslänge (s, höchstens {v.segment_frames_max} Frames)",
                     segment, segment, False),
                ):  # fmt: skip
                    info.params.add(
                        name=name, type="float", min=0.25, max=high, label=label, expert=expert,
                        number=round(value, 2),
                    )  # fmt: skip
            for name, p in wf.params.items():
                param = info.params.add(
                    name=name,
                    type=p.type,
                    required=p.required,
                    upload=p.upload,
                    multiple_of=p.multiple_of or 0,
                    choices=[str(c) for c in p.choices],
                    label=p.label,
                    expert=p.is_expert,
                    reference=p.reference,
                )
                if p.min is not None:
                    param.min = p.min
                if p.max is not None:
                    param.max = p.max
                default = graph[p.node]["inputs"].get(p.input)
                if p.upload or default is None:
                    continue
                if p.type == "int":
                    param.integer = int(default)
                elif p.type == "float":
                    param.number = float(default)
                else:
                    param.text = str(default)
        return msg.SerializeToString()

    async def _set_enabled(self, msg: commands_pb2.SetWorkflowEnabled, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        self._workflow(msg.workflow)
        self.manifest = await asyncio.to_thread(
            models.set_workflow_enabled, self.cfg.root, msg.workflow, msg.enabled
        )
        log.info("Workflow %s %s", msg.workflow, "aktiviert" if msg.enabled else "deaktiviert")
        return ""

    async def _open(self, msg: commands_pb2.OpenWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        lane = self._lane_of(self._workflow(msg.workflow))
        if lane is None or not lane.status.get("health"):
            return "Die ausführende ComfyUI-Instanz läuft nicht."
        await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, msg.workflow)
        return ""

    async def _adopt(self, msg: commands_pb2.AdoptWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        wf = self._workflow(msg.workflow)
        lane = self._lane_of(wf)
        if lane is None or not lane.status.get("health"):
            return "Die ausführende ComfyUI-Instanz läuft nicht (Node-Definitionen fehlen)."

        def adopt() -> models.Manifest:
            info = comfy.ComfyClient(lane.inst.url, timeout=120).object_info()
            edited = json.loads(lane.node.editor_file(wf.key).read_text(encoding="utf-8"))
            registry_ui = json.loads((self.manifest.root / "workflows" / wf.ui).read_text())
            api = comfy.ui_to_api(edited, info)
            if problems := comfy.check_graph(api, info, wf.runtime_inputs):
                raise comfy.ComfyError("; ".join(problems))
            changed = api != comfy.ui_to_api(registry_ui, info)
            man = models.replace_workflow_graph(
                self.cfg.root, wf.key, edited, api, reset_status=changed
            )
            comfy.install_editor_copy(self.cfg, man, wf.key, replace=True)
            return man

        self.manifest = await asyncio.to_thread(adopt)
        log.info("Workflow %s aus dem Editor übernommen", wf.key)
        return ""

    async def _create(self, msg: commands_pb2.CreateWorkflow, call: _Call) -> str:
        self._workflow(msg.source)
        self.manifest, key = await asyncio.to_thread(
            models.create_workflow, self.cfg.root, msg.source, msg.title
        )
        call.entity = f"workflow:{key}"
        if self._lane_of(self.manifest.workflows[key]) is not None:
            await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, key)
        log.info("Workflow %s als Kopie von %s angelegt", key, msg.source)
        return ""

    async def _delete(self, msg: commands_pb2.DeleteWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        wf = self._workflow(msg.workflow)
        active = comfy_pb2.JobsActive.FromString(self._jobs_active())
        if any(job.workflow == wf.key for job in active.jobs):
            return "Workflow hat laufende oder wartende Aufträge."
        lane = self._lane_of(wf)
        self.manifest = await asyncio.to_thread(models.delete_workflow, self.cfg.root, wf.key)
        if lane is not None:
            await asyncio.to_thread(lane.node.remove_editor_copy, wf.key)
        log.info("Workflow %s gelöscht (Registrierung, UI/API, Editor-Kopie)", wf.key)
        return ""

    @staticmethod
    def _add_lora(char: character_pb2.Character, lo, arch: str = "", active: bool = False) -> None:
        char.loras.add(
            arch=arch,
            active=active,
            strength=lo.strength,
            key=lo.key,
            base_engine=lo.base_engine,
            dataset=lo.dataset,
            trigger=lo.trigger,
            steps=lo.steps,
            rank=lo.rank,
            status=lo.status,
            created_at=lo.created_at,
        )

    async def _register_reference(self, rel: str, source: str) -> None:
        """Datei unter local/ als Vorlage führen (gleicher Inhalt = dieselbe Vorlage)."""
        digest = await asyncio.to_thread(pipeline.sha256_file, self.cfg.local / rel)
        _, new = self.store.add_reference(rel, digest, "image", source)
        if new:
            self.hub.push_events(spb.TOPIC_REFERENCE_ADDED)

    async def _delete_media(self, msg: commands_pb2.DeleteMedia, call: _Call) -> str:
        if not msg.media_ids:
            return "Keine Datei gewählt."
        call.entity = "media:" + ",".join(str(i) for i in msg.media_ids[:20])
        removed = await asyncio.to_thread(gallery.delete_media, self.cfg, list(msg.media_ids))
        # Freigewordene Pfade neu prüfen: ComfyUI vergibt gelöschte Dateinamen erneut.
        self._seen_media.difference_update(removed)
        self.hub.push_events(spb.TOPIC_MEDIA_REMOVED)
        log.info("Galerie: %d Datei(en) gelöscht", len(removed))
        return ""

    async def _media_content_tier(self, msg: commands_pb2.MediaContentTier, call: _Call) -> str:
        """Inhaltsstufe anheben (Befehl 43, Regel 13: nur anhebbar)."""
        call.entity = f"media:{msg.media_id}"
        self.store.raise_content_tier(msg.media_id)
        self.hub.push_events(spb.TOPIC_MEDIA_ADDED)  # geänderter Eintrag per Push
        return ""
