"""Einzige Konfigurationsquelle: ``local/config.toml`` plus Projektpfade und Logging."""

from __future__ import annotations

import ipaddress
import logging
import logging.handlers
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    """Claras Telegram-Konto über TDLib (V0 §6.1, C2d): ``api_id``/``api_hash`` und der
    Datenbankschlüssel im Schlüsselbund; Testbetrieb nur mit freigegebenen Chat-IDs; Antworttempo
    und Sendegrenze gegen Sperren."""

    tdjson: Path  # libtdjson (launcher/setup_tdlib.sh)
    data_dir: Path  # TDLib-Sitzung und -Dateien (nur für den Benutzer lesbar)
    api_id_service: str
    api_hash_service: str
    db_key_service: str
    test_mode: bool
    test_chat_ids: tuple[int, ...]
    max_download_mb: float
    reply_delay_min_s: float
    reply_delay_max_s: float
    typing_chars_per_s: float
    max_messages_per_minute: int


@dataclass(frozen=True)
class InstagramConfig:
    """Claras Instagram-Creator-Konto über die Instagram-API mit Instagram-Login (V0 §6, §6.1):
    App-ID, App-Geheimnis, Verify-Token, Zugangstoken und Medienschlüssel nur im Schlüsselbund;
    über den Tunnel öffentlich sind nur Webhook, OAuth-Rückruf und Medienabruf (§10 Punkt 1)."""

    public_base_url: str  # feste Tunnel-Adresse (https://…); leer = Tunnel nicht eingerichtet
    webhook_path: str
    oauth_path: str
    media_path: str
    graph_url: str
    graph_version: str
    oauth_authorize_url: str
    oauth_token_url: str
    scopes: tuple[str, ...]
    subscribed_fields: tuple[str, ...]
    app_id_service: str
    app_secret_service: str
    verify_token_service: str
    token_service: str
    token_expiry_service: str
    media_key_service: str
    max_download_mb: float
    max_image_mb: float
    max_video_mb: float
    max_audio_mb: float
    max_text_bytes: int
    media_url_ttl_s: float
    oauth_state_ttl_s: float
    token_refresh_margin_s: float
    token_refresh_retry_s: float
    check_s: float
    download_timeout_s: float
    profile_timeout_s: float
    reply_window_h: float
    human_agent_window_h: float
    max_messages_per_minute: int

    @property
    def redirect_uri(self) -> str:
        """OAuth-Rückruf; muss exakt so in der Meta-App eingetragen sein."""
        return self.public_base_url + self.oauth_path


@dataclass(frozen=True)
class TokenConfig:
    """BEP-20-Token auf BSC, das als Zahlungseingang beobachtet wird."""

    symbol: str
    contract: str  # EIP-55
    decimals: int
    price_id: str  # Kennung der Kursquelle


@dataclass(frozen=True)
class WalletConfig:
    """Claras öffentliche Adressen und die kostenlosen Datenquellen (V0 §8.5, C5a). Ungültige
    Adressen bleiben leer und erscheinen mit Grund im Reiter Wallet (``*_error``)."""

    btc_address: str
    btc_error: str
    bsc_address: str
    bsc_error: str
    btc_api: str
    bsc_rpc: str
    price_api: str
    btc_price_id: str
    tokens: tuple[TokenConfig, ...]
    btc_confirmations: int
    bsc_confirmations: int
    poll_s: float
    bsc_header_batch: int
    # Gültigkeit eines Angebots (eindeutiger Betrag) in Minuten (V0 §8.5 Punkt 2)
    offer_valid_min: int


@dataclass(frozen=True)
class ProductionConfig:
    """Aufträge mit Stufen (V0 §4.3): Kandidatenzahl und Wiederholungen je Stufe."""

    candidates_default: int
    candidates_max: int
    stage_attempts_max: int
    # Obergrenze der Gesamtlänge eines Videos in Sekunden (Abschnitte werden aneinandergereiht)
    video_max_s: float


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
    instagram: InstagramConfig | None  # None: Abschnitt fehlt (Kanal nicht eingerichtet)
    wallet: WalletConfig | None  # None: Abschnitt fehlt (Zahlungseingang nicht eingerichtet)

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


def _parse_telegram(tg: object, root: Path, path: Path) -> TelegramConfig | None:
    """[telegram_account]; fehlt der Abschnitt, ist der Kanal nicht eingerichtet."""
    if tg is None:
        return None
    w = "telegram_account"
    if not isinstance(tg, dict):
        raise ConfigError(f"Konfiguration {path}: [{w}] muss ein Abschnitt sein.")
    ids = tg.get("test_chat_ids", [])
    if not isinstance(ids, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in ids
    ):
        raise ConfigError(f"Konfiguration: {w}.test_chat_ids muss eine Liste von Chat-IDs sein.")
    test_mode = tg.get("test_mode", True)
    if not isinstance(test_mode, bool):
        raise ConfigError(f"Konfiguration: {w}.test_mode muss true oder false sein.")
    low = _positive(tg, "reply_delay_min_s", 4, w)
    high = _positive(tg, "reply_delay_max_s", 20, w)
    if low > high:
        raise ConfigError(f"Konfiguration: {w}.reply_delay_min_s > reply_delay_max_s.")
    return TelegramConfig(
        tdjson=root / str(tg.get("tdjson", "local/tdlib/libtdjson.dylib")),
        data_dir=root / str(tg.get("data_dir", "local/telegram")),
        api_id_service=str(tg.get("api_id_service", "darkfluenzer.telegram.api_id")),
        api_hash_service=str(tg.get("api_hash_service", "darkfluenzer.telegram.api_hash")),
        db_key_service=str(tg.get("db_key_service", "darkfluenzer.telegram.db_key")),
        test_mode=test_mode,
        test_chat_ids=tuple(ids),
        max_download_mb=_positive(tg, "max_download_mb", 2000, w),
        reply_delay_min_s=low,
        reply_delay_max_s=high,
        typing_chars_per_s=_positive(tg, "typing_chars_per_s", 6, w),
        max_messages_per_minute=int(_positive(tg, "max_messages_per_minute", 6, w)),
    )


# Erste Pfadsegmente des lokalen Cockpits; öffentliche Instagram-Pfade dürfen sie nie überdecken
_LOCAL_SEGMENTS = {"", "api", "ws", "assets", "healthz"}


def _https(t: dict, key: str, default: str, where: str) -> str:
    val = t.get(key, default)
    if not isinstance(val, str) or (val and not val.startswith("https://")):
        raise ConfigError(f"Konfiguration: {where}.{key} muss eine https://-Adresse sein.")
    return val.rstrip("/")


def _texts(t: dict, key: str, default: list[str], where: str) -> tuple[str, ...]:
    val = t.get(key, default)
    if not (isinstance(val, list) and val and all(isinstance(v, str) and v for v in val)):
        raise ConfigError(f"Konfiguration: {where}.{key} muss eine Liste von Texten sein.")
    return tuple(val)


def _parse_instagram(t: object, path: Path) -> InstagramConfig | None:
    """[instagram]; fehlt der Abschnitt, ist der Kanal nicht eingerichtet."""
    if t is None:
        return None
    w = "instagram"
    if not isinstance(t, dict):
        raise ConfigError(f"Konfiguration {path}: [{w}] muss ein Abschnitt sein.")
    paths = {}
    for key, default in (
        ("webhook_path", "/instagram/webhook"),
        ("oauth_path", "/instagram/oauth"),
        ("media_path", "/instagram/media"),
    ):
        val = t.get(key, default)
        if (
            not isinstance(val, str)
            or not val.startswith("/")
            or val.endswith("/")
            or val.split("/")[1] in _LOCAL_SEGMENTS
        ):
            raise ConfigError(
                f"Konfiguration: {w}.{key} muss ein eigener Pfad sein (z. B. '{default}')."
            )
        paths[key] = val
    if len(set(paths.values())) != len(paths):
        raise ConfigError(f"Konfiguration: {w}.webhook_path/oauth_path/media_path gleich.")
    version = t.get("graph_version", "v24.0")
    if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+", version):
        raise ConfigError(f"Konfiguration: {w}.graph_version muss z. B. 'v24.0' sein.")
    window = _positive(t, "reply_window_h", 24, w)
    human = _positive(t, "human_agent_window_h", 168, w)
    if human < window:
        raise ConfigError(f"Konfiguration: {w}.human_agent_window_h < reply_window_h.")
    graph = _https(t, "graph_url", "https://graph.instagram.com", w)
    authorize = _https(t, "oauth_authorize_url", "https://www.instagram.com/oauth/authorize", w)
    token_url = _https(t, "oauth_token_url", "https://api.instagram.com/oauth/access_token", w)
    if not (graph and authorize and token_url):
        raise ConfigError(f"Konfiguration: {w}: Meta-Adressen dürfen nicht leer sein.")
    base = _https(t, "public_base_url", "", w)
    if base and (urlsplit(base).path or urlsplit(base).query):
        raise ConfigError(f"Konfiguration: {w}.public_base_url nur mit Host, ohne Pfad.")
    return InstagramConfig(
        public_base_url=base,
        webhook_path=paths["webhook_path"],
        oauth_path=paths["oauth_path"],
        media_path=paths["media_path"],
        graph_url=graph,
        graph_version=version,
        oauth_authorize_url=authorize,
        oauth_token_url=token_url,
        scopes=_texts(
            t, "scopes", ["instagram_business_basic", "instagram_business_manage_messages"], w
        ),
        subscribed_fields=_texts(
            t, "subscribed_fields", ["messages", "messaging_seen", "messaging_postbacks"], w
        ),
        app_id_service=str(t.get("app_id_service", "darkfluenzer.instagram.app_id")),
        app_secret_service=str(t.get("app_secret_service", "darkfluenzer.instagram.app_secret")),
        verify_token_service=str(
            t.get("verify_token_service", "darkfluenzer.instagram.verify_token")
        ),
        token_service=str(t.get("token_service", "darkfluenzer.instagram.token")),
        token_expiry_service=str(
            t.get("token_expiry_service", "darkfluenzer.instagram.token_expiry")
        ),
        media_key_service=str(t.get("media_key_service", "darkfluenzer.instagram.media_key")),
        max_download_mb=_positive(t, "max_download_mb", 100, w),
        max_image_mb=_positive(t, "max_image_mb", 8, w),
        max_video_mb=_positive(t, "max_video_mb", 25, w),
        max_audio_mb=_positive(t, "max_audio_mb", 25, w),
        max_text_bytes=int(_positive(t, "max_text_bytes", 1000, w)),
        media_url_ttl_s=_positive(t, "media_url_ttl_s", 900, w),
        oauth_state_ttl_s=_positive(t, "oauth_state_ttl_s", 600, w),
        token_refresh_margin_s=_positive(t, "token_refresh_margin_s", 10 * 86400, w),
        token_refresh_retry_s=_positive(t, "token_refresh_retry_s", 3600, w),
        check_s=_positive(t, "check_s", 60, w),
        download_timeout_s=_positive(t, "download_timeout_s", 300, w),
        profile_timeout_s=_positive(t, "profile_timeout_s", 5, w),
        reply_window_h=window,
        human_agent_window_h=human,
        max_messages_per_minute=int(_positive(t, "max_messages_per_minute", 30, w)),
    )


def _parse_wallet(t: object, path: Path) -> WalletConfig | None:
    """[wallet]; Adressen werden auf Format und Prüfsumme geprüft (V0 §8.5 Punkt 1)."""
    from .payments.addresses import btc_address_error, evm_address_error

    if t is None:
        return None
    w = "wallet"
    if not isinstance(t, dict):
        raise ConfigError(f"Konfiguration {path}: [{w}] muss ein Abschnitt sein.")
    btc = str(t.get("btc_address", "")).strip()
    bsc = str(t.get("bsc_address", "")).strip()
    btc_err = btc_address_error(btc) if btc else ""
    bsc_err = evm_address_error(bsc) if bsc else ""
    tokens = []
    for symbol, spec in (t.get("tokens") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"Konfiguration: {w}.tokens.{symbol} muss eine Tabelle sein.")
        contract = str(spec.get("contract", ""))
        if err := evm_address_error(contract):
            raise ConfigError(f"Konfiguration: {w}.tokens.{symbol}.contract: {err}.")
        tokens.append(
            TokenConfig(
                symbol=symbol,
                contract=contract,
                decimals=int(_positive(spec, "decimals", 18, f"{w}.tokens.{symbol}")),
                price_id=str(spec.get("price_id", "")),
            )
        )
    return WalletConfig(
        btc_address="" if btc_err else btc,
        btc_error=btc_err,
        bsc_address="" if bsc_err else bsc,
        bsc_error=bsc_err,
        btc_api=str(t.get("btc_api", "https://mempool.space/api")).rstrip("/"),
        bsc_rpc=str(t.get("bsc_rpc", "https://bsc-dataseed.bnbchain.org")),
        price_api=str(t.get("price_api", "https://api.coingecko.com/api/v3/simple/price")),
        btc_price_id=str(t.get("btc_price_id", "bitcoin")),
        tokens=tuple(tokens),
        btc_confirmations=int(_positive(t, "btc_confirmations", 2, w)),
        bsc_confirmations=int(_positive(t, "bsc_confirmations", 15, w)),
        poll_s=_positive(t, "poll_s", 60, w),
        bsc_header_batch=int(_positive(t, "bsc_header_batch", 100, w)),
        offer_valid_min=int(_positive(t, "offer_valid_min", 60, w)),
    )


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
        video_max_s=float(_positive(prod, "video_max_s", 120, "production")),
    )
    if production.candidates_default > production.candidates_max:
        raise ConfigError("Konfiguration: production.candidates_default > candidates_max.")
    telegram = _parse_telegram(data.get("telegram_account"), root, path)
    instagram = _parse_instagram(data.get("instagram"), path)
    wallet = _parse_wallet(data.get("wallet"), path)
    return Config(
        root=root,
        comfyui=media,
        comfyui_ai=ai,
        server=_parse_server(data["server"]),
        telegram=telegram,
        instagram=instagram,
        wallet=wallet,
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
