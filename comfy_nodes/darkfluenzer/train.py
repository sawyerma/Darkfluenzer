"""LoRA-Training mit Wiederaufnahme-Checkpoints (SP3 Schritt 3) auf Basis von ComfyUIs
``TrainLoraNode`` (ComfyUI v0.45.3, gepinnt über ``launcher/setup_comfyui.sh``).

``TrainLoraNode`` legt je Lauf einen neuen Optimierer an; ``existing_lora`` lädt nur Gewichte. Dieser
Knoten führt denselben Trainingsweg aus und schreibt alle ``checkpoint_every`` Optimiererschritte
und am Ende einen vollständigen Checkpoint nach ``checkpoint_dir``: alle trainierten Parameter
(Gewichte und Bias), Optimiererzustand, Schrittzahl, Zufallszustand (Datenreihenfolge, Sigmas),
GradScaler und den bisherigen Verlauf. Startgewichte und Zufall kommen nur aus dem Seed, das
Rauschen je Schritt aus Seed und Schrittzahl: ein fortgesetzter Lauf ist bitgleich zum
durchgehenden (echter Lauf 17.11.2026). Ein neuer Lauf mit demselben Ordner und denselben
Einstellungen setzt beim letzten gültigen Checkpoint fort; mit Gesamtschritten gleich dem
Checkpoint endet er sofort mit dessen Gewichten („Beenden“). Konstante Lernrate:
``TrainLoraNode`` hat keinen Lernratenplan.

``checkpoint.json`` im Ordner nennt den letzten Checkpoint (Schritt, Gesamtschritte, Verlust) für
das Cockpit.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import comfy.utils
import comfy_extras.nodes_custom_sampler as custom_sampler
import comfy_extras.nodes_train as nt
import torch
from comfy_api.latest import io
from tqdm.auto import trange

PREFIX = "checkpoint_"
KEEP = 2  # so viele Checkpoints bleiben liegen (der letzte gültige und sein Vorgänger)
STATUS = "checkpoint.json"
SETTINGS = (
    "batch_size", "grad_accumulation_steps", "learning_rate", "rank", "optimizer",
    "loss_function", "seed", "training_dtype", "lora_dtype", "algorithm", "bucket_mode",
    "bypass_mode",
)  # fmt: skip


class _Run:
    """Checkpoint-Ordner, Abstand und gefundener Stand eines Trainingslaufs."""

    def __init__(self, folder: str, every: int, signature: str) -> None:
        self.folder = Path(folder) if folder else None
        self.every = every
        self.signature = signature
        self.resume = self._latest()
        self.total = 0

    def _files(self) -> list[Path]:
        if self.folder is None or not self.folder.is_dir():
            return []
        return sorted(self.folder.glob(f"{PREFIX}*.pt"), reverse=True)

    def _latest(self) -> dict | None:
        for path in self._files():
            try:
                # ComfyUI führt Knoten im inference_mode aus; so geladene Tensoren wären für
                # Optimierer und Gewichte nicht änderbar
                with torch.inference_mode(False):
                    data = torch.load(path, map_location="cpu", weights_only=True)
            except Exception as exc:  # unvollständig oder beschädigt: nächster älterer
                logging.warning("Darkfluenzer-Training: Checkpoint %s unbrauchbar: %s", path, exc)
                continue
            if data.get("signature") == self.signature:
                logging.info("Darkfluenzer-Training: setze bei Schritt %s fort (%s)", data["step"], path)
                return data
        return None

    def save(self, step: int, params: list, optimizer, scaler, losses: list[float]) -> None:
        if self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "signature": self.signature,
            "step": step,
            "params": [p.detach().to("cpu").clone() for p in params],
            "optimizer": _to_cpu(optimizer.state_dict()),
            "rng": torch.get_rng_state(),
            "mps_rng": torch.mps.get_rng_state() if torch.backends.mps.is_available() else None,
            "grad_scaler": scaler.state_dict() if scaler is not None else None,
            "losses": list(losses),
        }
        target = self.folder / f"{PREFIX}{step:08d}.pt"
        tmp = self.folder / f".{target.name}.tmp"
        torch.save(data, tmp)
        os.replace(tmp, target)  # erst vollständig geschrieben, dann gültig
        for old in self._files()[KEEP:]:
            old.unlink(missing_ok=True)
        status = {
            "step": step,
            "total": self.total,
            "file": target.name,
            "loss": losses[-1] if losses else None,
            "saved_at": time.time(),
        }
        tmp = self.folder / f".{STATUS}.tmp"
        tmp.write_text(json.dumps(status), encoding="utf-8")
        os.replace(tmp, self.folder / STATUS)


def _to_cpu(value):
    if isinstance(value, torch.Tensor):
        return value.detach().to("cpu").clone()
    if isinstance(value, dict):
        return {k: _to_cpu(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_cpu(v) for v in value]
    return value


def _sampler_class(run: _Run):
    class ResumableTrainSampler(nt.TrainSampler):
        """``TrainSampler`` mit Start bei einem Checkpoint und periodischem Speichern."""

        def sample(self, model_wrap, sigmas, extra_args, callback, noise, latent_image=None,
                   denoise_mask=None, disable_pbar=False):  # fmt: skip
            model_wrap.conds = nt.process_cond_list(model_wrap.conds)
            cond = model_wrap.conds["positive"]
            dataset_size = sigmas.size(0)
            params = [p for group in self.optimizer.param_groups for p in group["params"]]
            run.total = self.total_steps
            losses: list[float] = []
            start = 0
            if run.resume is not None:
                start = min(int(run.resume["step"]), self.total_steps)
                self.optimizer.load_state_dict(run.resume["optimizer"])
                torch.set_rng_state(run.resume["rng"])
                if run.resume.get("mps_rng") is not None and torch.backends.mps.is_available():
                    torch.mps.set_rng_state(run.resume["mps_rng"])
                if self.grad_scaler is not None and run.resume.get("grad_scaler"):
                    self.grad_scaler.load_state_dict(run.resume["grad_scaler"])
                for loss in run.resume.get("losses", []):  # Verlauf ohne Sprung
                    losses.append(loss)
                    if self.loss_callback:
                        self.loss_callback(loss)
            report = self.loss_callback

            def record(loss: float) -> None:
                losses.append(loss)
                if report:
                    report(loss)

            self.loss_callback = record
            ui_pbar = comfy.utils.ProgressBar(self.total_steps)
            ui_pbar.update_absolute(start)
            pbar = trange(start, self.total_steps, desc="Training LoRA", smoothing=0.01,
                          disable=not comfy.utils.PROGRESS_BAR_ENABLED)  # fmt: skip
            for i in pbar:
                noisegen = custom_sampler.Noise_RandomNoise(
                    self.seed + i * 1000
                )
                if self.bucket_latents is not None:
                    self._train_step_bucket_mode(model_wrap, cond, extra_args, noisegen, latent_image, pbar)
                elif self.real_dataset is None:
                    self._train_step_standard_mode(model_wrap, cond, extra_args, noisegen, latent_image,
                                                   dataset_size, pbar)  # fmt: skip
                else:
                    self._train_step_multires_mode(model_wrap, cond, extra_args, noisegen, latent_image,
                                                   dataset_size, pbar)  # fmt: skip
                if (i + 1) % self.grad_acc == 0:
                    if self.grad_scaler is not None:
                        self.grad_scaler.unscale_(self.optimizer)
                    for group in self.optimizer.param_groups:
                        for param in group["params"]:
                            if param.grad is not None:
                                param.grad.data = param.grad.data.to(param.data.dtype)
                    if self.grad_scaler is not None:
                        self.grad_scaler.step(self.optimizer)
                        self.grad_scaler.update()
                    else:
                        self.optimizer.step()
                    self.optimizer.zero_grad()
                    done = (i + 1) // self.grad_acc
                    if run.every and (done % run.every == 0 or i + 1 == self.total_steps):
                        run.save(i + 1, params, self.optimizer, self.grad_scaler, losses)
                ui_pbar.update(1)  # prüft auch einen Abbruch durch den Betreiber
            return torch.zeros_like(latent_image)

    return ResumableTrainSampler


@contextlib.contextmanager
def _resumable(run: _Run):
    """Setzt während eines Laufs Sampler und Optimierer-Anlage von ``nodes_train`` auf die
    fortsetzbaren Fassungen (ComfyUI führt Aufträge nacheinander aus)."""
    sampler, create = nt.TrainSampler, nt._create_optimizer

    def optimizer(name, parameters, learning_rate):
        params = list(parameters)
        opt = create(name, params, learning_rate)
        if run.resume is not None:
            saved = run.resume["params"]
            if len(saved) != len(params) or any(
                s.shape != p.shape for s, p in zip(saved, params, strict=True)
            ):
                raise RuntimeError("Checkpoint passt nicht zu diesem Modell und Rang.")
            with torch.no_grad():
                for p, s in zip(params, saved, strict=True):
                    p.copy_(s.to(p.device, p.dtype))
            # Optimiererzustand erst beim Trainingsstart: ComfyUI legt die Parameter danach auf
            # das Rechengerät, der Zustand muss dort liegen (sonst cpu/mps gemischt)
        return opt

    nt.TrainSampler, nt._create_optimizer = _sampler_class(run), optimizer
    try:
        yield
    finally:
        nt.TrainSampler, nt._create_optimizer = sampler, create


def _shapes(value) -> list:
    """Form der Trainingslatents (Liste, Latent-Dict oder Tensor) für die Signatur."""
    if isinstance(value, dict):
        return _shapes(value.get("samples"))
    if isinstance(value, (list, tuple)):
        return [_shapes(v) for v in value]
    return list(getattr(value, "shape", ()))


def _signature(inputs: dict, latents: list) -> str:
    """Einstellungen und Datensatzform; die Gesamtschritte gehören nicht dazu (Verlängern und
    Beenden setzen beim selben Checkpoint an)."""
    settings = {k: inputs[k][0] for k in SETTINGS}
    shapes = _shapes(latents)
    blob = json.dumps({"settings": settings, "latents": shapes}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class TrainLoraResumable(nt.TrainLoraNode):
    """``TrainLoraNode`` mit vollständigen Checkpoints und Fortsetzen."""

    @classmethod
    def define_schema(cls):
        schema = nt.TrainLoraNode.define_schema()
        schema.node_id = "DarkfluenzerTrainLora"
        schema.display_name = "Darkfluenzer · LoRA trainieren (Checkpoints)"
        schema.category = "Darkfluenzer/Training"
        schema.inputs = [
            *schema.inputs,
            io.String.Input("checkpoint_dir", default="",
                            tooltip="Ordner der Checkpoints; setzt das Backend je Figur und Datensatz."),
            io.Int.Input("checkpoint_every", default=100, min=0, max=100000,
                         tooltip="Checkpoint alle n Optimiererschritte (0 = keiner)."),
        ]  # fmt: skip
        return schema

    @classmethod
    def execute(cls, checkpoint_dir, checkpoint_every, **inputs):
        if inputs["existing_lora"][0] != "[None]":
            raise ValueError("Fortsetzen geht über checkpoint_dir, nicht über existing_lora.")
        run = _Run(checkpoint_dir[0], int(checkpoint_every[0]), _signature(inputs, inputs["latents"]))
        # Startgewichte, Datenreihenfolge und Sigmas nur aus dem Seed: derselbe Lauf ist
        # wiederholbar (TrainLoraNode nutzt sonst den Zufallszustand des ComfyUI-Prozesses)
        torch.manual_seed(int(inputs["seed"][0]))
        with _resumable(run):
            return nt.TrainLoraNode.execute.__func__(cls, **inputs)
