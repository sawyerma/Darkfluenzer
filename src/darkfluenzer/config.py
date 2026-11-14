"""Einzige Konfigurationsquelle: ``local/config.toml`` plus Projektpfade und Logging."""

from __future__ import annotations

import ipaddress
import logging
import logging.handlers
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("darkfluenzer.config")

CONFIG_RELATIVE = Path("local") / "config.toml"


class ConfigError(Exception):
    """Konfiguration fehlt oder ist ungültig. Die Meldung ist für Menschen formuliert."""


@dataclass(frozen=True)
class ComfyConfig:
    path: Path
    python: Path
    host: str
    port: int
    extra_args: tuple[str, ...]
    path_prepend: tuple[str, ...]
    env: dict[str, str]
    startup_timeout_s: float
    stop_timeout_s: float

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True)
class Config:
    root: Path
    comfyui: ComfyConfig

    @property
    def local(self) -> Path:
        return self.root / "local"

    @property
    def logs(self) -> Path:
        return self.local / "logs"


def project_root() -> Path:
    """Projektordner: ``DARKFLUENZER_ROOT`` oder der Checkout, aus dem das Paket geladen wurde."""
    env = os.environ.get("DARKFLUENZER_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _resolve(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p


def _require(table: dict, key: str, typ: type | tuple[type, ...], where: str):
    if key not in table:
        raise ConfigError(f"Konfiguration: '{where}.{key}' fehlt.")
    value = table[key]
    # bool ist ein int-Subtyp und darf nicht als Zahl durchrutschen
    if isinstance(value, bool) and bool not in (typ if isinstance(typ, tuple) else (typ,)):
        raise ConfigError(f"Konfiguration: '{where}.{key}' hat den falschen Typ.")
    if not isinstance(value, typ):
        raise ConfigError(f"Konfiguration: '{where}.{key}' hat den falschen Typ.")
    return value


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_comfy(root: Path, t: dict) -> ComfyConfig:
    w = "comfyui"
    host = _require(t, "host", str, w)
    if not _loopback(host):
        raise ConfigError(f"Konfiguration: comfyui.host='{host}' ist keine Loopback-Adresse.")
    port = _require(t, "port", int, w)
    if not 1 <= port <= 65535:
        raise ConfigError(f"Konfiguration: comfyui.port={port} ist ungültig.")
    extra = t.get("extra_args", [])
    prepend = t.get("path_prepend", [])
    env = t.get("env", {})
    if not (isinstance(extra, list) and all(isinstance(a, str) for a in extra)):
        raise ConfigError("Konfiguration: comfyui.extra_args muss eine Liste von Texten sein.")
    if not (isinstance(prepend, list) and all(isinstance(a, str) for a in prepend)):
        raise ConfigError("Konfiguration: comfyui.path_prepend muss eine Liste von Texten sein.")
    if not (isinstance(env, dict) and all(isinstance(v, str) for v in env.values())):
        raise ConfigError("Konfiguration: [comfyui.env] darf nur Text-Werte enthalten.")
    reserved = {"--listen", "--port", "--auto-launch"}
    if reserved & {a.split("=")[0] for a in extra}:
        raise ConfigError(
            "Konfiguration: --listen/--port/--auto-launch werden vom Launcher gesetzt "
            "und dürfen nicht in comfyui.extra_args stehen."
        )
    wm = env.get("PYTORCH_MPS_HIGH_WATERMARK_RATIO")
    if wm is not None:
        try:
            ratio = float(wm)
        except ValueError as exc:
            raise ConfigError(
                f"Konfiguration: PYTORCH_MPS_HIGH_WATERMARK_RATIO='{wm}' ist keine Zahl."
            ) from exc
        if ratio < 0:
            raise ConfigError("Konfiguration: PYTORCH_MPS_HIGH_WATERMARK_RATIO muss >= 0 sein.")
        if ratio == 0:
            log.warning("PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0 hebt die MPS-Speichergrenze auf.")

    startup = t.get("startup_timeout_s", 240)
    stop = t.get("stop_timeout_s", 30)
    for name, val in (("startup_timeout_s", startup), ("stop_timeout_s", stop)):
        if isinstance(val, bool) or not isinstance(val, int | float) or val <= 0:
            raise ConfigError(f"Konfiguration: comfyui.{name} muss eine positive Zahl sein.")

    return ComfyConfig(
        path=_resolve(root, _require(t, "path", str, w)),
        python=_resolve(root, _require(t, "python", str, w)),
        host=host,
        port=port,
        extra_args=tuple(extra),
        path_prepend=tuple(prepend),
        env=dict(env),
        startup_timeout_s=float(startup),
        stop_timeout_s=float(stop),
    )


def load(root: Path | None = None) -> Config:
    root = (root or project_root()).resolve()
    path = root / CONFIG_RELATIVE
    if not path.is_file():
        raise ConfigError(
            f"Konfigurationsdatei fehlt: {path}. Vorlage: config.example.toml nach "
            "local/config.toml kopieren und Pfade anpassen."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Konfigurationsdatei {path} ist kein gültiges TOML: {exc}") from exc
    if not isinstance(data.get("comfyui"), dict):
        raise ConfigError(f"Konfiguration {path}: Abschnitt [comfyui] fehlt.")
    return Config(root=root, comfyui=_parse_comfy(root, data["comfyui"]))


def setup_logging(cfg: Config, name: str = "darkfluenzer.log") -> Path:
    """Rotierendes technisches Log unter ``local/logs`` (keine Chat-Volltexte)."""
    cfg.logs.mkdir(parents=True, exist_ok=True)
    target = cfg.logs / name
    root_logger = logging.getLogger("darkfluenzer")
    if not any(getattr(h, "baseFilename", None) == str(target) for h in root_logger.handlers):
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s pid=%(process)d %(message)s")
        )
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    return target
