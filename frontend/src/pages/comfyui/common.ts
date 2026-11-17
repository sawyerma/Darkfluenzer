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

export const WORKFLOW_TONE: Record<string, Tone> = { PASS: "ok", OFFEN: "neutral", GESPERRT: "bad" };

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
