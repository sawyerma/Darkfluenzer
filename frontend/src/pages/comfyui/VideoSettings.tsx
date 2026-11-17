import type { ReactNode } from "react";
import type { WorkflowParam } from "../../core/generated/darkfluenzer/v1/comfy_pb";

/** Reihenfolge der Videofelder; die Abschnittslänge liefert das Backend nur, wenn die Engine
 * Abschnitte nutzt (Modus frames). */
export const VIDEO_ORDER = ["duration_s", "fps", "width", "height", "segment_s"];

/** Einheitliche Videosteuerung (SP1 Schritt 10): alle Video-Workflows zeigen dieselben Felder an
 * derselben Stelle, direkt unter Prompt und Startbild; Grenzen kommen aus dem STATE. */
export function VideoSettings({ params, field }: { params: readonly WorkflowParam[]; field: (p: WorkflowParam) => ReactNode }) {
  const byName = new Map(params.map((p) => [p.name, p]));
  return <>{VIDEO_ORDER.flatMap((name) => (byName.has(name) ? [field(byName.get(name)!)] : []))}</>;
}
