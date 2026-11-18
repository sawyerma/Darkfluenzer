import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { clock } from "./common";
import { useStateTopic } from "../../core/state";

const KIND: Record<string, string> = { studio: "KI-Studio", chat: "Kunde", test: "Kundentest", warmup: "Aufwärmen" };
const seconds = (s: number) => `${s.toFixed(1).replace(".", ",")} s`;

/** KI-Status (STATE 11, SP4 Schritt 1): geladenes Modell, ob es geladen bleibt, laufende Sprachläufe,
 *  Aufwärmlauf nach dem Start der Instanz und die letzten Läufe (nur Zeiten, keine Inhalte). */
export function KiStatus() {
  const topic = useStateTopic(Topic.AI_STATUS);
  const st = topic?.value;
  if (!st) return null;
  if (!st.configured) return <small>KI-Instanz (ComfyUI 2) nicht eingerichtet.</small>;
  return (
    <div className="g-control-part" data-stale={topic.staleSince !== null || undefined}>
      <div className="g-line g-head">
        <h2>KI-Status</h2>
        <span className="g-value">
          {st.keepLoaded ? (
            <span className="g-badge" title="Zulassung entlädt die KI-Instanz nie ([comfyui_ai] keep_loaded)">
              BLEIBT GELADEN
            </span>
          ) : null}
          {st.running ? (
            <span className="g-badge" data-tone="ok">
              {st.running} LÄUFT
            </span>
          ) : null}
        </span>
      </div>
      <dl className="g-params">
        <div>
          <dt>Modell</dt>
          <dd>{st.engine || "nicht geladen"}</dd>
        </div>
        <div>
          <dt>Aufwärmen</dt>
          <dd>
            {st.warmupMs
              ? st.warmupError
                ? `fehlgeschlagen: ${st.warmupError}`
                : `${seconds(st.warmupS)} · ${clock(Number(st.warmupMs))}`
              : "seit dem Start noch nicht"}
          </dd>
        </div>
        <div>
          <dt>Letzte Läufe</dt>
          <dd>
            {st.recent.length
              ? st.recent.map((r) => `${KIND[r.kind] ?? r.kind} ${r.failed ? "Fehler" : seconds(r.totalS)}`).join(" · ")
              : "noch keine"}
          </dd>
        </div>
      </dl>
    </div>
  );
}
