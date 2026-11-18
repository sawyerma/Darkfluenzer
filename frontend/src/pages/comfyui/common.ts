import { ComfyState, JobResult } from "../../core/generated/darkfluenzer/v1/comfy_pb";

type Tone = "ok" | "warn" | "bad" | "neutral";

export const STATE_LABEL: Record<ComfyState, [string, Tone]> = {
  [ComfyState.UNSPECIFIED]: ["UNBEKANNT", "neutral"],
  [ComfyState.STOPPED]: ["GESTOPPT", "neutral"],
  [ComfyState.STARTING]: ["STARTET", "warn"],
  [ComfyState.READY]: ["BEREIT", "ok"],
  [ComfyState.BUSY]: ["ARBEITET", "ok"],
  [ComfyState.STOPPING]: ["STOPPT", "warn"],
  [ComfyState.UNREACHABLE]: ["NICHT ERREICHBAR", "bad"],
  [ComfyState.FAILED]: ["FEHLER", "bad"],
};

/** Nachweisstatus aus dem Manifest statt bloßem PASS (GUI-Prüfung 18.11. Punkt 7):
 *  [Abzeichen, Ton, Kurztext, Erklärung]. Workflow: Abnahme-Render des registrierten Graphen – ein
 *  geänderter Graph fällt auf OFFEN zurück (models.replace_workflow_graph); GESPERRT nimmt das Backend
 *  nicht an. LoRA: nach dem Training OFFEN bis zur Freigabe. */
type Gate = [string, Tone, string, string];
export const WORKFLOW_GATE: Record<string, Gate> = {
  PASS: ["RENDER GEPRÜFT", "ok", "Render geprüft", "Abnahme-Render dieses registrierten Graphen bestanden (Manifest PASS); nach einer Graph-Änderung wieder ungeprüft."],
  OFFEN: ["UNGEPRÜFT", "neutral", "ungeprüft", "Noch kein abgenommener Render dieses Graphen (Manifest OFFEN)."],
  FAIL: ["RENDER FEHLGESCHLAGEN", "bad", "Render fehlgeschlagen", "Abnahme-Render fehlgeschlagen (Manifest FAIL)."],
  GESPERRT: ["GESPERRT", "bad", "gesperrt", "Gesperrt (Manifest GESPERRT): das Backend nimmt keinen Render an."],
};
export const LORA_GATE: Record<string, Gate> = {
  PASS: ["FREIGEGEBEN", "ok", "freigegeben", "Nach Prüfung freigegeben (Manifest PASS)."],
  OFFEN: ["NICHT FREIGEGEBEN", "neutral", "nicht freigegeben", "Trainiert; Prüfung und Freigabe offen (Manifest OFFEN)."],
  FAIL: ["PRÜFUNG NICHT BESTANDEN", "bad", "Prüfung nicht bestanden", "Prüfung nicht bestanden (Manifest FAIL)."],
  GESPERRT: ["GESPERRT", "bad", "gesperrt", "Gesperrt (Manifest GESPERRT): nicht aktivierbar."],
};
export function gate(map: Record<string, Gate>, status: string): Gate {
  return map[status] ?? [status || "UNBEKANNT", "neutral", status || "unbekannt", ""];
}

export const LABEL: Record<string, string> = {
  video: "Abschnitte",
  negative_prompt: "Negativ-Prompt",
  seed: "Seed",
  steps: "Schritte",
  cfg: "CFG",
  width: "Breite",
  height: "Höhe",
  denoise: "Stärke",
  mask_grow: "Maskenrand (px)",
  mask: "Maske",
};

export const IMAGE = /\.(png|jpe?g|webp)$/i;

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("de-DE");
}

export const INSTANCE_LABEL: Record<string, string> = { media: "ComfyUI 1 · Medien", ai: "ComfyUI 2 · KI" };

export const RESULT_BADGE: Record<JobResult, [string, Tone]> = {
  [JobResult.UNSPECIFIED]: ["UNBEKANNT", "neutral"],
  [JobResult.DONE]: ["FERTIG", "ok"],
  [JobResult.FAILED]: ["FEHLER", "bad"],
  [JobResult.CANCELLED]: ["ABGEBROCHEN", "neutral"],
};

export const VIDEO = /\.(mp4|webm|mov)$/i;

export const PHOTO_STATUS: Record<string, string> = {
  incomplete: "wird kopiert",
  unsupported: "Format",
  unreadable: "nicht lesbar",
  duplicate: "doppelt",
  too_small: "zu klein",
};

export const STAGE_LABEL: Record<string, [string, Tone]> = {
  running: ["LÄUFT", "ok"],
  waiting: ["AUSWAHL", "warn"],
  done: ["FERTIG", "ok"],
  failed: ["FEHLER", "bad"],
  cancelled: ["ABGEBROCHEN", "neutral"],
};

/** Dauer als kurzer Text (Schätzungen in der Warteschlange, SP1 Schritt 2). */
export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}
