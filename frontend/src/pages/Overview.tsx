import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useStateTopic } from "../core/state";
import { clock } from "./ComfyUI";

// Übersicht (F7.1): Informationskarten nur aus echtem Backendzustand. Kundenakten und Freigaben
// folgen mit den Kanälen (PHASENPLAN_V0 C2/C5).
export function Overview() {
  const active = useStateTopic(Topic.JOBS_ACTIVE);
  const jobs = active?.value.jobs ?? [];
  const running = jobs.find((j) => j.running);
  const stale = active?.staleSince ?? null;
  return (
    <section className="g-panel">
      <h1>Übersicht</h1>
      <div className="g-cards">
        <div className="g-card g-kpi" data-stale={stale !== null || undefined}>
          <small>GPU-Warteschlange</small>
          <strong>{active ? jobs.length : "–"}</strong>
          <small>
            {running ? `läuft: ${running.jobId ? running.workflow : "Auftrag aus der ComfyUI-Oberfläche"}` : jobs.length ? "wartet" : "leer"}
            {active?.value.paused ? " · angehalten" : ""}
            {stale !== null ? ` · veraltet seit ${clock(stale)}` : ""}
          </small>
        </div>
      </div>
    </section>
  );
}
