"""Renderbahnen, Zulassung, Warteschlange, Instanzen (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import os

from ..core import orders
from ..media import gallery, models, pipeline, training
from ..nodes import comfy
from ..nodes import local as runtime
from ..v1 import (
    comfy_pb2,
    commands_pb2,
)
from ..v1 import stream_pb2 as spb
from .base import _Call, _Lane, log


def _param_text(name: str, value: object) -> str:
    """Job-Parameter für die Anzeige; der Abschnittsplan eines Langvideos als eine Zeile."""
    if name == "video" and isinstance(value, dict):
        frames = value.get("frames") or []
        joined = " + ".join(map(str, frames))
        return f"{len(frames)} Abschnitt(e) · Frames {joined} · {value.get('fps', 0):g} fps"
    return str(value)


class RenderMixin:
    """Renderbahnen, Zulassung, Warteschlange, Instanzen; Teil von ``Cockpit``."""

    def _lane_of(self, wf: models.Workflow) -> _Lane | None:
        """Bahn der Instanz, die diesen Workflow ausführt (None: Instanz nicht eingerichtet)."""
        return self.lanes.get(self.manifest.engines[wf.engine].instance)

    def _lane_of_job(self, job_id: int) -> _Lane:
        wf = self.manifest.workflows.get(self.store.job(job_id)["workflow"])
        return (self._lane_of(wf) if wf else None) or self.lanes["media"]

    def enqueue_existing(self) -> None:
        """Nach einem Neustart: bei ComfyUI eingereichte Jobs abholen statt neu rendern
        (prompt_id), nie eingereichte erneut einreihen, angelegte in Reihenfolge fortsetzen."""
        for job_id, pid in self.store.running_jobs():
            if pid and pid != os.getpid() and runtime.pid_alive(pid):
                continue  # ein anderer Prozess (z. B. CLI-Evaluation) führt ihn aus
            if self.store.job(job_id)["prompt_id"]:
                self._resuming.add(job_id)
                self._lane_of_job(job_id).renders.put_nowait(job_id)
            else:
                self.store.requeue_job(job_id)
        for job_id, _ in self.store.queued_jobs():
            self._lane_of_job(job_id).renders.put_nowait(job_id)

    async def render_worker(self, lane: _Lane) -> None:
        """Führt die Renderjobs einer Instanz nacheinander (FIFO) aus; vor jedem Start prüft die
        gemeinsame Zulassung den freien Speicher (§4.2)."""
        while True:
            job_id = await lane.renders.get()
            await lane.resume.wait()  # angehalten: nächster Job wartet
            job = self.store.job(job_id)
            status = job["status"]
            if status != "queued" and not (status == "running" and job_id in self._resuming):
                continue  # inzwischen entfernt
            self._resuming.discard(job_id)
            engine = job["engine"]
            eng = self.manifest.engines.get(engine)
            modelfree = eng is not None and eng.modelfree  # lässt geladene Modelle in Ruhe
            if not modelfree and not await self._admit(lane, job_id, engine):
                continue  # während des Wartens auf Speicher entfernt
            lane.running_job = job_id
            try:
                await asyncio.to_thread(
                    pipeline.run_render,
                    self.cfg,
                    self.manifest,
                    job_id,
                    client_id=lane.client_id,
                    is_cancelled=lambda job=job_id: job in self._cancelled,
                    unload_first=bool(lane.engine) and lane.engine != engine and not modelfree,
                )
            except Exception as exc:  # im Journal als fehlgeschlagen festgehalten
                log.error("Renderjob %s fehlgeschlagen: %s", job_id, exc)
            lane.engine, lane.running_job = lane.engine if modelfree else engine, 0
            if job_id in self._cancelled:  # abgebrochen: Modelle entladen, Speicher frei
                self._cancelled.discard(job_id)
                client = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.timeout_s)
                try:
                    await asyncio.to_thread(client.free)
                    lane.engine = ""
                except comfy.ComfyError as exc:
                    log.warning("Speicherfreigabe nach Abbruch von Job %s: %s", job_id, exc)
            orders.advance_order(self.store, job_id)  # Stufe vollständig? (SQLite im Loop)
            if (stage_id := self.store.job(job_id).get("stage_id")) is not None:
                self._cloner_delivery(self.store.stage(stage_id).order_id)
            self._orders_changed()
            self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
            self.hub.push_events(spb.TOPIC_MEDIA_ADDED)
            self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
            self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())

    def _need_gb(self, engine: str) -> float:
        """Speicherbedarf einer Engine: gemessene Spitze des letzten Laufs, bis zur ersten
        Messung die Summe ihrer Modelldateien."""
        if (peak := self.store.engine_peak_gb(engine)) is not None:
            return peak
        return sum(mf.size for mf in self.manifest.engine_files(engine)) / 1e9

    async def _admit(self, lane: _Lane, job_id: int, engine: str) -> bool:
        """Zulassung (§4.2): startet erst, wenn nach dem Bedarf die Reserve frei bleibt. Ist sie zu
        knapp, entlädt eine ruhende andere Instanz ihre Modelle; sonst wartet der Auftrag.
        False: der Auftrag wurde während des Wartens entfernt."""
        need = self._need_gb(engine)
        if lane.engine == engine:
            return True  # gleiche Engine: Modelle sind bereits geladen
        while True:
            if self.store.job(job_id)["status"] not in ("queued", "running"):
                lane.waiting_job, lane.need_gb = 0, 0.0
                self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
                return False
            free = (await asyncio.to_thread(self._measure)).get("ram_free", 0) / 2**30
            if not free or free - need >= self.cfg.server.memory_reserve_gb:
                break
            idle = [
                other
                for other in self.lanes.values()
                if other is not lane and other.engine and not other.running_job
            ]
            if idle:
                for other in idle:
                    await asyncio.to_thread(comfy.ComfyClient(other.inst.url).free)
                    log.info(
                        "Zulassung: %s entlädt %s für Auftrag %s",
                        other.inst.name,
                        other.engine,
                        job_id,
                    )
                    other.engine = ""
                continue
            if not any(o.running_job for o in self.lanes.values() if o is not lane):
                # nichts mehr freizugeben und keine andere Instanz arbeitet: Warten hilft nicht
                log.warning(
                    "Zulassung: Auftrag %s braucht %.1f GB, frei %.1f GB (Reserve %.0f GB) – "
                    "nichts mehr freizugeben, Start",
                    job_id,
                    need,
                    free,
                    self.cfg.server.memory_reserve_gb,
                )
                break
            lane.waiting_job, lane.need_gb = job_id, round(need, 1)
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
            await asyncio.sleep(self.cfg.server.observe_s)
        if lane.waiting_job:
            lane.waiting_job, lane.need_gb = 0, 0.0
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
        return True

    def _measure(self) -> dict:
        """Freier Unified Memory (über eine erreichbare Instanz) und macOS-Swap."""
        for lane in self.lanes.values():
            if lane.status.get("health"):
                try:
                    self._memory = lane.node.memory(self.cfg.server.observe_s)
                except comfy.ComfyError:
                    continue
                return self._memory
        self._memory = {"swap": next(iter(self.lanes.values())).node.swap_mb()}
        return self._memory

    async def observe(self) -> None:
        """Beobachtet ComfyUI, Modelldateien und Job-Journal; gepusht wird nur bei Änderung."""
        while True:
            try:
                await self.refresh_comfy()
                await asyncio.to_thread(self._measure)
                self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
                async with self._registry:
                    if fingerprint := await asyncio.to_thread(self._reload_if_changed):
                        self._registry_version = self.store.bump("workflows", fingerprint)
                    workflows = await asyncio.to_thread(self._workflows)
                self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
                await self.refresh_characters()
                self.hub.set_state(spb.TOPIC_ORDERS_ACTIVE, self._orders_active())
                self.hub.set_state(spb.TOPIC_CHANNELS, self._channels())
                self.hub.set_state(spb.TOPIC_WALLET, self._wallet_state())
                self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())
                self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
                self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
                await asyncio.to_thread(
                    gallery.scan_media, self.cfg, self._seen_media, self.cfg.server.media_settle_s
                )
                self.hub.push_events(spb.TOPIC_MEDIA_ADDED)
            except Exception:  # eine fehlerhafte Runde beendet die Beobachtung nicht
                log.exception("Beobachtung fehlgeschlagen")
            await asyncio.sleep(self.cfg.server.observe_s)

    async def progress_listener(self, lane: _Lane) -> None:
        """Fortschritt (z. B. Sampler-Schritte) der eigenen Aufträge aus ComfyUIs WebSocket in die
        Warteschlange übernehmen; bei Verbindungsverlust nach der Beobachtungspause erneut."""
        while True:
            if lane.status.get("health"):
                try:
                    async for prompt_id, value, maximum in comfy.progress_events(
                        lane.inst.url, lane.client_id
                    ):
                        if maximum:
                            lane.progress[prompt_id] = (value, maximum)
                        else:
                            lane.progress.pop(prompt_id, None)
                        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
                except Exception as exc:  # ComfyUI beendet/neu gestartet: später neu verbinden
                    log.debug("ComfyUI-Fortschritt %s getrennt: %s", lane.inst.name, exc)
            await asyncio.sleep(self.cfg.server.observe_s)

    def _read_queue(self, lane: _Lane) -> list[tuple[int, bool, str]]:
        client = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.observe_s)
        try:
            return client.queued_jobs()
        except comfy.ComfyError:
            return []

    def _jobs_active(self) -> bytes:
        """FIFO-Sicht je Instanz: ComfyUI (läuft, wartet), danach angelegte, noch nicht
        übergebene Jobs."""
        queued = [job_id for job_id, _ in self.store.queued_jobs()]
        in_comfy = [job_id for lane in self.lanes.values() for job_id, _, _ in lane.queue if job_id]
        ids = in_comfy + [j for j in queued if j not in in_comfy]
        brief = self.store.jobs_brief(ids) if ids else {}
        msg = comfy_pb2.JobsActive(
            paused=[n for n, lane in self.lanes.items() if not lane.resume.is_set()],
            version=self.store.domain_version("jobs"),
        )

        def add(lane: _Lane, job_id: int, running: bool, prompt_id: str = "") -> None:
            workflow, params = brief.get(job_id, ("", {}))
            value, maximum = lane.progress.get(prompt_id, (0, 0)) if running else (0, 0)
            job = msg.jobs.add(
                job_id=job_id,
                workflow=workflow,
                running=running,
                progress_value=value,
                progress_max=maximum,
                instance=lane.inst.name,
            )
            job.params.update({k: _param_text(k, v) for k, v in params.items()})

        for lane in self.lanes.values():
            for job_id, running, prompt_id in lane.queue:
                add(lane, job_id, running, prompt_id)
        for job_id in queued:
            if job_id not in in_comfy:
                add(self._lane_of_job(job_id), job_id, False)
        return msg.SerializeToString()

    def _resources(self) -> bytes:
        mem = self._memory
        msg = comfy_pb2.Resources(
            ram_total_gb=round(mem.get("ram_total", 0) / 2**30, 1),
            ram_free_gb=round(mem.get("ram_free", 0) / 2**30, 1),
            swap_used_mb=round(mem.get("swap", 0.0), 1),
            reserve_gb=self.cfg.server.memory_reserve_gb,
        )
        for lane in self.lanes.values():
            msg.instances.add(
                name=lane.inst.name,
                engine=lane.engine,
                waiting_job=lane.waiting_job,
                need_gb=lane.need_gb,
            )
        return msg.SerializeToString()

    def _instances(self) -> bytes:
        msg = comfy_pb2.ComfyInstances()
        for lane in self.lanes.values():
            msg.instances.append(self._comfy_status(lane))
        return msg.SerializeToString()

    def _comfy_status(self, lane: _Lane) -> comfy_pb2.ComfyStatus:
        st = lane.status
        health = st.get("health") or {}
        running = sum(1 for _, r, _ in lane.queue if r)
        if lane.busy == "start":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif lane.busy == "stop":
            state = comfy_pb2.COMFY_STATE_STOPPING
        elif health and st.get("state") in ("running", "foreign"):
            state = comfy_pb2.COMFY_STATE_BUSY if running else comfy_pb2.COMFY_STATE_READY
            lane.error = ""
        elif st.get("state") == "starting":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif st.get("state") == "stopped":
            state = comfy_pb2.COMFY_STATE_FAILED if lane.error else comfy_pb2.COMFY_STATE_STOPPED
        else:  # unhealthy, fremder Prozess ohne ComfyUI-Antwort, Prüffehler
            state = comfy_pb2.COMFY_STATE_UNREACHABLE
        return comfy_pb2.ComfyStatus(
            state=state,
            managed=bool(st.get("managed")),
            url=lane.inst.url,
            version=health.get("comfyui_version") or "",
            device=health.get("device_type") or "",
            error=lane.error,
            queue_running=running,
            queue_pending=len(lane.queue) - running,
            name=lane.inst.name,
        )

    async def refresh_comfy(self) -> None:
        for lane in self.lanes.values():
            try:
                lane.status = await asyncio.to_thread(lane.node.status)
            except runtime.RuntimeFailure as exc:
                lane.status = {"state": "error", "managed": False}
                lane.error = str(exc)
            lane.queue = (
                await asyncio.to_thread(self._read_queue, lane) if lane.status.get("health") else []
            )
            queued = {prompt_id for _, _, prompt_id in lane.queue}
            lane.progress = {p: v for p, v in lane.progress.items() if p in queued}
        self.hub.set_state(spb.TOPIC_COMFY_INSTANCES, self._instances())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def _cancel(self, msg: commands_pb2.CancelJob, call: _Call) -> str:
        call.entity = f"job:{msg.job_id}"
        job = self.store.job(msg.job_id)
        if job["status"] == "queued":
            self.store.set_job_status(
                msg.job_id, "failed", error="Aus der Warteschlange entfernt.", cancelled=True
            )
            log.info("Job %s aus der Warteschlange entfernt", msg.job_id)
            orders.advance_order(self.store, msg.job_id)
            self._orders_changed()
            return ""
        if job["status"] != "running":
            return "Auftrag ist bereits abgeschlossen."
        # gilt ab dem Klick (BUG-043): vor der Übermittlung verwirft die Pipeline den Start,
        # bei der Übermittlung bricht sie sofort ab, ein trotzdem fertiges Ergebnis wird verworfen
        self._cancelled.add(msg.job_id)
        lane = self._lane_of_job(msg.job_id)
        prompt = next((p for j, _, p in lane.queue if j == msg.job_id), "") or job["prompt_id"]
        if prompt:
            client = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.timeout_s)
            await asyncio.to_thread(client.cancel, prompt)
        log.info("Job %s abgebrochen (prompt %s)", msg.job_id, prompt or "noch nicht übermittelt")
        return ""

    async def _pause(self, msg: commands_pb2.PauseQueue, call: _Call) -> str:
        name = msg.instance or "media"
        call.entity = f"comfyui:{name}"
        lane = self.lanes.get(name)
        if lane is None:
            return f"ComfyUI-Instanz '{name}' ist nicht eingerichtet."
        if msg.paused:
            lane.resume.clear()
        else:
            lane.resume.set()
        self.store.adapter_set("comfyui", name, "paused", "1" if msg.paused else "0")  # BUG-046
        log.info("Warteschlange %s %s", name, "angehalten" if msg.paused else "fortgesetzt")
        return ""

    def _comfy_command(self, which: str, name: str, call: _Call) -> str:
        call.entity = f"comfyui:{name}"
        lane = self.lanes.get(name)
        if lane is None:
            return f"ComfyUI-Instanz '{name}' ist nicht eingerichtet."
        if lane.busy:
            return "Ein Befehl für diese ComfyUI-Instanz läuft bereits"
        if lane.status.get("state") == "foreign":
            return "Port belegt durch eine nicht von Darkfluenzer gestartete Instanz"
        if which == "comfy_stop" and (lane.running_job or lane.queue):
            return "Instanz arbeitet – erst nach dem laufenden Auftrag stoppen."
        action = "start" if which == "comfy_start" else "stop"
        lane.busy, lane.error = action, ""
        self.hub.set_state(spb.TOPIC_COMFY_INSTANCES, self._instances())
        task = asyncio.create_task(self._run(lane, action, call.request_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ""

    async def _run(self, lane: _Lane, action: str, request_id: str) -> None:
        fn = lane.node.start if action == "start" else lane.node.stop
        try:
            await asyncio.to_thread(fn)
        except runtime.RuntimeFailure as exc:
            log.error("ComfyUI %s %s fehlgeschlagen: %s", lane.inst.name, action, exc)
            lane.error = str(exc)
        finally:
            lane.busy = ""
        if action == "stop":
            lane.engine = ""  # gestoppt: keine Modelle mehr geladen
        self.store.finish_command(
            request_id, "failed" if lane.error else "completed", detail=lane.error
        )
        self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
        await self.refresh_comfy()

    def _enqueue(self, jobs: list[int]) -> None:
        for job_id in jobs:
            lane = self._lane_of_job(job_id)
            lane.renders.put_nowait(job_id)

    async def _render(self, msg: commands_pb2.Render, call: _Call) -> str:
        wf = self._workflow(msg.workflow)
        call.entity = f"workflow:{wf.key}"
        lane = self._lane_of(wf)
        if lane is None:
            return "Die ausführende ComfyUI-Instanz ist nicht eingerichtet."
        if reason := await asyncio.to_thread(self._not_startable, wf):
            return reason
        values = {
            v.name: getattr(v, v.WhichOneof("value")) for v in msg.values if v.WhichOneof("value")
        }
        inputs = {}
        if msg.repeat_job_id:  # Wiederholen/Variieren: Parameter und Eingaben des Ursprungsjobs
            origin = self.store.job(msg.repeat_job_id)
            if origin["workflow"] != wf.key:
                return (
                    f"Auftrag {msg.repeat_job_id} gehört zu {origin['workflow']}, nicht {wf.key}."
                )
            for name, value in origin["params"].items():
                if name in wf.params and wf.params[name].upload:
                    inputs[name] = value
                elif name in wf.params or name in pipeline.VIDEO_KEYS:
                    values.setdefault(name, value)
        inputs.update(await self._inputs(wf, msg.files))
        dataset = None
        if wf.training:  # Datensatzversion der geeigneten Bilder des gewählten Charakters
            if not msg.character_id:
                return "Für ein Training einen Charakter wählen."
            folders = self._folders(self.store.character(msg.character_id))
            path = await asyncio.to_thread(training.build_dataset, folders)
            dataset = path.relative_to(self.cfg.local).as_posix()
        job_id = pipeline.create_render(
            self.store,
            self.manifest,
            wf.key,
            values,
            inputs,
            video_max_s=self.cfg.production.video_max_s,
            dataset=dataset,
            parent_media_id=msg.parent_media_id or None,
            command={
                "request_id": call.request_id,
                "payload_sha": call.payload_sha,
                "command": call.name,
                "status": "accepted",
            },
        )
        call.entity, call.recorded = f"job:{job_id}", True
        log.info("Renderjob %s (%s, %s) eingereiht", job_id, wf.key, lane.inst.name)
        lane.renders.put_nowait(job_id)
        return ""

    async def _inputs(self, wf: models.Workflow, files) -> dict[str, str]:
        """Eingabedateien eines Befehls: Galerie-Medium per ID (SHA-256 geprüft), Vorlage aus der
        Bibliothek oder Upload; Vorlagen-Parameter landen zusätzlich in der Bibliothek (C1)."""
        inputs: dict[str, str] = {}
        for f in files:
            p = wf.params.get(f.param)
            if p is None or not p.upload:
                raise pipeline.PipelineError(f"{f.param}: kein Upload-Parameter von {wf.key}.")
            if f.reference_id:
                if not p.reference:
                    raise pipeline.PipelineError(f"{f.param}: hier wird keine Vorlage erwartet.")
                ref = self.store.reference(f.reference_id)
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.input_from_file, self.cfg, ref["path"], ref["sha256"]
                )
                source = f"reference:{f.reference_id}"
            elif f.media_id:  # exakte Galerie-Datei über ihre unveränderliche ID
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.input_from_media, self.cfg, f.media_id
                )
                source = f"media:{f.media_id}"
            else:
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.store_input, self.cfg, f.data, f.filename
                )
                source = "upload"
            if p.reference:
                await self._register_reference(inputs[f.param], source)
        return inputs

    def _workflow(self, key: str) -> models.Workflow:
        wf = self.manifest.workflows.get(key)
        if wf is None:
            raise models.ManifestError(f"Workflow '{key}' ist nicht registriert.")
        return wf

    def _not_startable(self, wf: models.Workflow) -> str:
        """Gates vor einem neuen Job: Betreiberschalter, Abnahme-Sperre, Modellbereitschaft."""
        if not wf.enabled:
            return "Workflow ist deaktiviert."
        if wf.status == "GESPERRT":
            return "Workflow ist gesperrt."
        eng = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"][wf.engine]
        return "" if eng["ready"] else f"Modelle fehlen ({eng['missing_gb']:.1f} GB)."
