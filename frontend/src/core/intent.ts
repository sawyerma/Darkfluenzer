import type { MediaItem } from "./generated/darkfluenzer/v1/media_pb";

// Übergabe aus Dateien in den ComfyUI-Reiter (Weiterverarbeiten, Video erstellen): genau dieses
// Medium als Eingabebild des gewählten Workflows. Wird beim Öffnen des Reiters einmal übernommen.
export interface RenderIntent {
  workflow: string;
  media: MediaItem;
  /** Eingang, der das Medium erhält (Standard „image“; „Als Vorlage“: der Vorlagen-Parameter) */
  param?: string;
}

let pending: RenderIntent | null = null;

export function setRenderIntent(intent: RenderIntent): void {
  pending = intent;
  window.location.hash = "#comfyui";
}

export function takeRenderIntent(): RenderIntent | null {
  const intent = pending;
  pending = null;
  return intent;
}

// Übergabe aus der Auftragskarte (Nachrichten) in den ComfyUI-Reiter: bezahlter Kundenauftrag, der
// dort mit einem Workflow der Inhaltsstufe standard produziert wird (V0 §8.4 Punkt 5).
let pendingOrder = "";

export function setProductionIntent(orderNo: string): void {
  pendingOrder = orderNo;
  window.location.hash = "#comfyui";
}

export function takeProductionIntent(): string {
  const orderNo = pendingOrder;
  pendingOrder = "";
  return orderNo;
}
