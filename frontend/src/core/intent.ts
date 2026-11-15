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
