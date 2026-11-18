import type { AiRun } from "../../core/generated/darkfluenzer/v1/ai_pb";
import type { WorkflowInfo } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useEventTopic } from "../../core/state";

/** Freie Default-Anweisungen (SP4 Schritt 4): letzte Deutungen des registrierten Workflows mit
 *  Anweisung, Ergebnis-JSON und Fehler; die Anweisung (Schema) steht im Graphen. */
export function Instructions({ workflow }: { workflow: WorkflowInfo }) {
  const results = useEventTopic(Topic.AI_RESULT);
  const runs = (results?.items ?? [])
    .map((e) => e.value.run)
    .filter((r): r is AiRun => !!r && r.kind === "instruction")
    .slice(-10)
    .reverse();
  return (
    <div className="g-workmain">
      <div className="g-line g-head">
        <h2>{workflow.title}</h2>
        <span className="g-badge">{workflow.status}</span>
      </div>
      <p className="g-note">Nachrichten ohne Kurzbefehl im Default-Chat; ausgeführt wird nur Erlaubtes.</p>
      <table className="g-table" aria-label="Letzte Deutungen">
        <thead>
          <tr>
            <th>Lauf</th>
            <th>Anweisung</th>
            <th>Ergebnis</th>
            <th>s</th>
          </tr>
        </thead>
        <tbody>
          {runs.length ? (
            runs.map((r) => (
              <tr key={String(r.runId)}>
                <td>#{String(r.runId)}</td>
                <td>{r.message}</td>
                <td className="g-mono">{r.error ? <span className="g-error">{r.error}</span> : r.answer}</td>
                <td>{r.totalS.toFixed(1)}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={4}>Noch keine Deutung.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
