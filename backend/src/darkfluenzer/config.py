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


# Instanzen (PHASENPLAN_V0 §4.2): Medien-ComfyUI 1 und KI-ComfyUI 2 mit eigenem Abschnitt
INSTANCE_SECTIONS = {"media": "comfyui", "ai": "comfyui_ai"}
# Eigene Verzeichnisse einer Instanz mit data_dir (Code und Modellablage werden geteilt)
DATA_DIR_ARGS = {
    "--user-directory": "user",
    "--input-directory": "input",
    "--output-directory": "output",
    "--temp-directory": "temp",
}


@dataclass(frozen=True)
class ComfyConfig:
    name: str  # "media" | "ai"
    path: Path
    python: Path
    host: str
    port: int
    extra_args: tuple[str, ...]
    path_prepend: tuple[str, ...]
    env: dict[str, str]
    startup_timeout_s: float
    stop_timeout_s: float
    data_dir: Path | None  # eigene user/input/output/temp-Ordner; None = ComfyUI-Standard

    def folder(self, sub: str) -> Path:
        """Eigener Ordner der Instanz (user, input, output, temp)."""
        return (self.data_dir if self.data_dir is not None else self.path) / sub

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def _file(self, suffix: str) -> str:
        # Medien-Instanz behält die bisherigen Namen; jede weitere Instanz bekommt eigene
        return f"comfyui{suffix}" if self.name == "media" else f"comfyui_{self.name}{suffix}"

    @property
    def state_name(self) -> str:
        return self._file(".json")

    @property
    def lock_name(self) -> str:
        return self._file(".lock")

    @property
    def log_name(self) -> str:
        return self._file(".log")


@dataclass(frozen=True)
class ServerConfig:
    """Lokaler Cockpit-Server: React-Build, Protobuf-WebSocket und Befehle auf einem Origin."""

    host: str
    port: int
    heartbeat_s: float
    observe_s: float
    catchup_limit: int
    timeout_s: float
    max_upload_mb: float
    media_settle_s: float
    client_queue_max: int
    memory_reserve_gb: float

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram-Adapter (V0 §6): Bot-Token im Schlüsselbund, Long-Polling ohne öffentlichen
    Zugang; api_base auch für einen lokalen Bot-API-Server (größere Dateien)."""

    keychain_service: str
    api_base: str
    poll_timeout_s: float
    max_download_mb: float
    send_timeout_s: float


@dataclass(frozen=True)
class ProductionConfig:
    """Aufträge mit Stufen (V0 §4.3): Kandidatenzahl und Wiederholungen je Stufe."""

    candidates_default: int
    candidates_max: int
    stage_attempts_max: int


@dataclass(frozen=True)
class IdentityConfig:
    """Gesichtsprüfung (identity.py): kleinere oder unsicherere Gesichter sind „nicht prüfbar“."""

    min_face_px: int
    min_score: float


@dataclass(frozen=True)
class Config:
    root: Path
    comfyui: ComfyConfig  # Medien-Instanz (immer vorhanden)
    comfyui_ai: ComfyConfig | None  # KI-Instanz, sobald [comfyui_ai] konfiguriert ist
    server: ServerConfig
    identity: IdentityConfig
    production: ProductionConfig
    telegram: TelegramConfig | None  # None: Abschnitt fehlt (Kanal nicht eingerichtet)

    @property
    def instances(self) -> tuple[ComfyConfig, ...]:
        return (self.comfyui,) + ((self.comfyui_ai,) if self.comfyui_ai else ())

    def instance(self, name: str) -> ComfyConfig:
        found = next((c for c in self.instances if c.name == name), None)
        if found is None:
            raise ConfigError(f"ComfyUI-Instanz '{name}' ist nicht eingerichtet ([comfyui_ai]).")
        return found

    @property
    def local(self) -> Path:
        return self.root / "local"

    @property
    def logs(self) -> Path:
        return self.local / "logs"


def project_root() -> Path:
    """Projektordner: ``DARKFLUENZER_ROOT`` oder der Checkout, aus dem das Paket geladen wurde
    (``<projekt>/backend/src/darkfluenzer/config.py``)."""
    env = os.environ.get("DARKFLUENZER_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


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


def _parse_comfy(root: Path, t: dict, name: str) -> ComfyConfig:
    w = INSTANCE_SECTIONS[name]
    host = _require(t, "host", str, w)
    if not _loopback(host):
        raise ConfigError(f"Konfiguration: {w}.host='{host}' ist keine Loopback-Adresse.")
    port = _require(t, "port", int, w)
    if not 1 <= port <= 65535:
        raise ConfigError(f"Konfiguration: {w}.port={port} ist ungültig.")
    extra = t.get("extra_args", [])
    prepend = t.get("path_prepend", [])
    env = t.get("env", {})
    if not (isinstance(extra, list) and all(isinstance(a, str) for a in extra)):
        raise ConfigError(f"Konfiguration: {w}.extra_args muss eine Liste von Texten sein.")
    if not (isinstance(prepend, list) and all(isinstance(a, str) for a in prepend)):
        raise ConfigError(f"Konfiguration: {w}.path_prepend muss eine Liste von Texten sein.")
    if not (isinstance(env, dict) and all(isinstance(v, str) for v in env.values())):
        raise ConfigError(f"Konfiguration: [{w}.env] darf nur Text-Werte enthalten.")
    data_dir = t.get("data_dir")
    if data_dir is not None and not isinstance(data_dir, str):
        raise ConfigError(f"Konfiguration: {w}.data_dir muss ein Pfad (Text) sein.")
    reserved = {"--listen", "--port", "--auto-launch", *(DATA_DIR_ARGS if data_dir else ())}
    if reserved & {a.split("=")[0] for a in extra}:
        raise ConfigError(
            f"Konfiguration: {', '.join(sorted(reserved))} werden vom Launcher gesetzt "
            f"und dürfen nicht in {w}.extra_args stehen."
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
    for key, val in (("startup_timeout_s", startup), ("stop_timeout_s", stop)):
        if isinstance(val, bool) or not isinstance(val, int | float) or val <= 0:
            raise ConfigError(f"Konfiguration: {w}.{key} muss eine positive Zahl sein.")

    return ComfyConfig(
        name=name,
        path=_resolve(root, _require(t, "path", str, w)),
        python=_resolve(root, _require(t, "python", str, w)),
        host=host,
        port=port,
        extra_args=tuple(extra),
        path_prepend=tuple(prepend),
        env=dict(env),
        startup_timeout_s=float(startup),
        stop_timeout_s=float(stop),
        data_dir=_resolve(root, data_dir) if data_dir else None,
    )


def _positive(t: dict, key: str, default: float, where: str) -> float:
    val = t.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int | float) or val <= 0:
        raise ConfigError(f"Konfiguration: {where}.{key} muss eine positive Zahl sein.")
    return float(val)


def _parse_server(t: dict) -> ServerConfig:
    w = "server"
    host = _require(t, "host", str, w)
    if not _loopback(host):
        raise ConfigError(f"Konfiguration: server.host='{host}' ist keine Loopback-Adresse.")
    port = _require(t, "port", int, w)
    if not 1 <= port <= 65535:
        raise ConfigError(f"Konfiguration: server.port={port} ist ungültig.")
    return ServerConfig(
        host=host,
        port=port,
        heartbeat_s=_positive(t, "heartbeat_s", 15, w),
        observe_s=_positive(t, "observe_s", 2, w),
        catchup_limit=int(_positive(t, "catchup_limit", 200, w)),
        timeout_s=_positive(t, "timeout_s", 20, w),
        max_upload_mb=_positive(t, "max_upload_mb", 50, w),
        media_settle_s=_positive(t, "media_settle_s", 10, w),
        client_queue_max=int(_positive(t, "client_queue_max", 2000, w)),
        memory_reserve_gb=_positive(t, "memory_reserve_gb", 16, w),
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
    for section in ("comfyui", "server"):
        if not isinstance(data.get(section), dict):
            raise ConfigError(f"Konfiguration {path}: Abschnitt [{section}] fehlt.")
    media = _parse_comfy(root, data["comfyui"], "media")
    ai = None
    if "comfyui_ai" in data:
        if not isinstance(data["comfyui_ai"], dict):
            raise ConfigError(f"Konfiguration {path}: [comfyui_ai] muss ein Abschnitt sein.")
        ai = _parse_comfy(root, data["comfyui_ai"], "ai")
        if ai.port == media.port:
            raise ConfigError(
                "Konfiguration: comfyui_ai.port muss sich von comfyui.port unterscheiden."
            )
        if ai.data_dir is None:
            raise ConfigError(
                "Konfiguration: comfyui_ai.data_dir fehlt (eigene Ordner der KI-Instanz)."
            )
    ident = data.get("identity", {})
    if not isinstance(ident, dict):
        raise ConfigError(f"Konfiguration {path}: [identity] muss ein Abschnitt sein.")
    score = _positive(ident, "min_score", 0.8, "identity")
    if score > 1:
        raise ConfigError("Konfiguration: identity.min_score muss zwischen 0 und 1 liegen.")
    prod = data.get("production", {})
    if not isinstance(prod, dict):
        raise ConfigError(f"Konfiguration {path}: [production] muss ein Abschnitt sein.")
    production = ProductionConfig(
        candidates_default=int(_positive(prod, "candidates_default", 3, "production")),
        candidates_max=int(_positive(prod, "candidates_max", 6, "production")),
        stage_attempts_max=int(_positive(prod, "stage_attempts_max", 3, "production")),
    )
    if production.candidates_default > production.candidates_max:
        raise ConfigError("Konfiguration: production.candidates_default > candidates_max.")
    tg = data.get("telegram")
    if tg is not None and not isinstance(tg, dict):
        raise ConfigError(f"Konfiguration {path}: [telegram] muss ein Abschnitt sein.")
    telegram = (
        TelegramConfig(
            keychain_service=str(tg.get("keychain_service", "darkfluenzer.telegram.bot_token")),
            api_base=str(tg.get("api_base", "https://api.telegram.org")).rstrip("/"),
            poll_timeout_s=_positive(tg, "poll_timeout_s", 50, "telegram"),
            max_download_mb=_positive(tg, "max_download_mb", 20, "telegram"),
            send_timeout_s=_positive(tg, "send_timeout_s", 60, "telegram"),
        )
        if tg is not None
        else None
    )
    return Config(
        root=root,
        comfyui=media,
        comfyui_ai=ai,
        server=_parse_server(data["server"]),
        telegram=telegram,
        identity=IdentityConfig(
            min_face_px=int(_positive(ident, "min_face_px", 64, "identity")), min_score=score
        ),
        production=production,
    )


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
