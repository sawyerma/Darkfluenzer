import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { useSyncExternalStore } from "react";
import {
  ClientMessageSchema,
  ServerMessageSchema,
  WelcomeStatus,
  type ServerMessage,
  type Welcome,
} from "./generated/darkfluenzer/v1/stream_pb";
import { acceptTopics, applyEvent, applyState, catchupComplete, markStale } from "./state";

// EIN binärer WebSocket zum eigenen Backend (PHASENPLAN_FRONT_V1 F3): Sitzung, Hello/Welcome,
// Heartbeat-Überwachung, Reconnect mit begrenztem Backoff und Jitter. Kein Polling, kein JSON.

const PROTOCOL_MAJOR = 1;
const PROTOCOL_MINOR = 0;
const HANDSHAKE_TIMEOUT_MS = 5_000;
const MISSED_HEARTBEATS = 2;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;
const RECONNECT_JITTER_MS = 500;
const CLOSE_POLICY = 1008; // Backend meldet Protokollverletzung: nicht erneut verbinden
const RELOAD_MARK = "darkfluenzer.reloadedForSchema";

export type ConnectionStatus = "CONNECTING" | "OPEN" | "STALE" | "BLOCKED";

export interface ConnectionInfo {
  status: ConnectionStatus;
  reason: string;
  // Zahl der angenommenen Verbindungen (Welcome); ändert sich mit jedem Reconnect.
  opened: number;
}

let info: ConnectionInfo = { status: "CONNECTING", reason: "", opened: 0 };
let csrf = "";
let ws: WebSocket | null = null;
let running = false; // Verbindungsversuch läuft oder Socket ist offen
let welcomed = false;
let heartbeatMs = 0;
let lastFrameMs = 0;
let attempt = 0;
let handshakeTimer: ReturnType<typeof setTimeout> | undefined;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let liveness: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function setStatus(status: ConnectionStatus, reason = ""): void {
  info = { status, reason, opened: info.opened + (status === "OPEN" ? 1 : 0) };
  for (const fn of listeners) fn();
}

/** Sitzung (HttpOnly-Cookie) herstellen und CSRF-Token für Befehle holen. */
// Bis zur ersten Sitzung die Vorgabe aus config.example.toml, danach der Wert des Backends.
let commandWait = 30_000;

export async function refreshSession(): Promise<string> {
  const resp = await fetch("/api/v1/session", { credentials: "same-origin", cache: "no-store" });
  const token = resp.headers.get("X-CSRF-Token");
  if (!resp.ok || !token) throw new Error(`Sitzung nicht verfügbar (HTTP ${resp.status})`);
  csrf = token;
  const wait = Number(resp.headers.get("X-Command-Wait-S"));
  if (wait > 0) commandWait = wait * 1000;
  return token;
}

/** Wartezeit auf die Quittung eines Befehls (Backend-Konfiguration server.command_wait_s). */
export function commandWaitMs(): number {
  return commandWait;
}

export function csrfToken(): string {
  return csrf;
}

/** Idempotent: startet die Verbindung, solange sie nicht blockiert ist. */
export function connect(): void {
  if (running || info.status === "BLOCKED") return;
  running = true;
  clearTimeout(retryTimer);
  setStatus("CONNECTING");
  void open();
}

async function open(): Promise<void> {
  try {
    await refreshSession();
  } catch (e) {
    lost(e instanceof Error ? e.message : String(e));
    return;
  }
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/v1/stream`;
  const socket = new WebSocket(url);
  socket.binaryType = "arraybuffer";
  ws = socket;
  welcomed = false;

  socket.onopen = () => {
    send({
      msg: {
        case: "hello",
        value: { protocolMajor: PROTOCOL_MAJOR, protocolMinor: PROTOCOL_MINOR, schemaId: __DF_SCHEMA_ID__ },
      },
    });
    handshakeTimer = setTimeout(() => {
      if (!welcomed) socket.close();
    }, HANDSHAKE_TIMEOUT_MS);
  };
  socket.onmessage = (ev: MessageEvent) => {
    if (ws !== socket) return;
    let msg: ServerMessage;
    try {
      msg = fromBinary(ServerMessageSchema, new Uint8Array(ev.data as ArrayBuffer));
    } catch {
      block("Antwort des Backends nicht lesbar (Schema)");
      return;
    }
    lastFrameMs = Date.now();
    try {
      dispatch(msg);
    } catch (e) {
      block(`Daten nicht anwendbar: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  socket.onclose = (ev: CloseEvent) => {
    if (ws !== socket) return;
    ws = null;
    if (info.status === "BLOCKED") return;
    if (ev.code === CLOSE_POLICY) block(ev.reason || "Protokollverletzung");
    else lost("Verbindung getrennt");
  };
}

function dispatch(msg: ServerMessage): void {
  const m = msg.msg;
  if (!welcomed) {
    if (m.case !== "welcome") throw new Error("Welcome erwartet");
    onWelcome(m.value);
    return;
  }
  switch (m.case) {
    case "stateFull":
      applyState(m.value);
      return;
    case "event":
      applyEvent(m.value);
      return;
    case "catchupComplete":
      catchupComplete(m.value);
      return;
    case "heartbeat":
      return; // lastFrameMs ist bereits aktualisiert
    default:
      throw new Error(`unerwarteter Frame ${m.case ?? "leer"}`);
  }
}

function onWelcome(w: Welcome): void {
  welcomed = true;
  clearTimeout(handshakeTimer);
  if (w.status === WelcomeStatus.REJECTED_SCHEMA) {
    // Backend wurde aktualisiert: einmal das passende Frontend laden, danach blockieren.
    if (sessionStorage.getItem(RELOAD_MARK) !== w.schemaId) {
      sessionStorage.setItem(RELOAD_MARK, w.schemaId);
      location.reload();
      return;
    }
    block(`${w.rejectReason} – Frontend neu bauen`);
    return;
  }
  if (w.status !== WelcomeStatus.ACCEPTED) {
    block(w.rejectReason || "Protokoll inkompatibel");
    return;
  }
  const accepted = acceptTopics(w.topics);
  if ("error" in accepted) {
    block(accepted.error);
    return;
  }
  sessionStorage.removeItem(RELOAD_MARK);
  attempt = 0;
  heartbeatMs = w.heartbeatIntervalMs;
  for (const s of accepted.subscribe) {
    send({ msg: { case: "subscribe", value: { topic: s.topic, afterCursor: s.afterCursor } } });
  }
  clearInterval(liveness);
  liveness = setInterval(checkLiveness, heartbeatMs);
  setStatus("OPEN");
}

function checkLiveness(): void {
  if (info.status === "OPEN" && Date.now() - lastFrameMs > heartbeatMs * (MISSED_HEARTBEATS + 1)) {
    ws?.close();
    lost("Heartbeat ausgeblieben");
  }
}

function send(init: MessageInitShape<typeof ClientMessageSchema>): void {
  ws?.send(toBinary(ClientMessageSchema, create(ClientMessageSchema, init)));
}

/** Verbindung verloren: Daten als veraltet kennzeichnen und mit Backoff neu verbinden. */
function lost(reason: string): void {
  clearInterval(liveness);
  clearTimeout(handshakeTimer);
  ws = null;
  running = false;
  markStale();
  setStatus("STALE", reason);
  const backoff = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempt);
  attempt += 1;
  retryTimer = setTimeout(connect, backoff + Math.random() * RECONNECT_JITTER_MS);
}

function block(reason: string): void {
  clearInterval(liveness);
  clearTimeout(handshakeTimer);
  clearTimeout(retryTimer);
  const socket = ws;
  ws = null;
  running = false;
  markStale();
  setStatus("BLOCKED", reason);
  socket?.close();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkLiveness();
  });
}

export function connectionInfo(): ConnectionInfo {
  return info;
}

export function useConnection(): ConnectionInfo {
  return useSyncExternalStore((fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, connectionInfo);
}
