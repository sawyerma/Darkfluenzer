import { ComfyState, type ComfyStatus } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { INSTANCE_LABEL, STATE_LABEL, clock } from "./common";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useCommand } from "../../core/commands";
import { useStateTopic } from "../../core/state";

/** Zustand einer ComfyUI-Instanz; veraltete Werte sind als solche gekennzeichnet. */
function ComfyBadge({ status, staleSince }: { status: ComfyStatus | undefined; staleSince: number | null }) {
  if (!status) return <span className="g-badge">KEINE DATEN</span>;
  const [label, tone] = STATE_LABEL[status.state];
  return (
    <>
      {staleSince !== null ? <small>veraltet seit {clock(staleSince)}</small> : null}
      <span className="g-badge" data-tone={staleSince !== null ? "stale" : tone}>
        {label}
      </span>
    </>
  );
}

/** URL einer bereiten Instanz (für „Öffnen“ im Editor), sonst leer. */
export function readyUrl(s: ComfyStatus | undefined, live: boolean): string {
  return live && (s?.state === ComfyState.READY || s?.state === ComfyState.BUSY) ? s.url : "";
}

/** Eine Instanz: echter Zustand, Start/Stopp nur der eigenen Instanz. */
function InstanceCard({ s, staleSince, live }: { s: ComfyStatus; staleSince: number | null; live: boolean }) {
  const cmd = useCommand();
  const url = readyUrl(s, live);
  const showStart = s.state === ComfyState.STOPPED || s.state === ComfyState.FAILED;
  // Stoppen nur ohne laufenden Auftrag und nur die eigene Instanz
  const showStop = s.managed && (s.state === ComfyState.READY || s.state === ComfyState.UNREACHABLE);
  const port = s.url ? new URL(s.url).port : "";
  return (
    <div className="g-card">
      <div className="g-line">
        <strong>
          {INSTANCE_LABEL[s.name] ?? s.name}
          {port ? ` · ${port}` : ""}
        </strong>
        <span className="g-value">
          {s.queueRunning + s.queuePending > 0 ? (
            <small>
              {s.queueRunning} läuft · {s.queuePending} wartet
            </small>
          ) : null}
          <ComfyBadge status={s} staleSince={staleSince} />
        </span>
      </div>
      {s.version ? (
        <small>
          {s.version} · {s.device}
          {s.managed ? "" : " · nicht von Darkfluenzer gestartet"}
        </small>
      ) : null}
      {s.error ? (
        <p className="g-note" role="alert">
          {s.error}
        </p>
      ) : null}
      <div className="g-actions">
        {showStart ? (
          <button
            type="button"
            className="g-button g-primary"
            disabled={!live || cmd.pending}
            onClick={() => cmd.run({ case: "comfyStart", value: { instance: s.name } })}
          >
            Starten
          </button>
        ) : null}
        {showStop ? (
          <button
            type="button"
            className="g-button"
            disabled={!live || cmd.pending}
            onClick={() => cmd.run({ case: "comfyStop", value: { instance: s.name } })}
          >
            Stoppen
          </button>
        ) : null}
        {url ? (
          <a className="g-button" href={url} target="_blank" rel="noreferrer">
            ComfyUI öffnen
          </a>
        ) : null}
      </div>
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

/** Instanzen (F7.5, rechts unten) mit gemeinsamem Speicher und Zulassung (V0 §4.2). */
export function Instances({ live }: { live: boolean }) {
  const instances = useStateTopic(Topic.COMFY_INSTANCES);
  const res = useStateTopic(Topic.RESOURCES)?.value;
  const waiting = res?.instances.filter((i) => i.waitingJob) ?? [];
  return (
    <div className="g-control-part">
      <h2>Instanzen</h2>
      {instances ? (
        instances.value.instances.map((s) => <InstanceCard key={s.name} s={s} staleSince={instances.staleSince} live={live} />)
      ) : (
        <span className="g-badge">KEINE DATEN</span>
      )}
      {res && res.ramTotalGb ? (
        <small>
          Speicher frei {res.ramFreeGb} von {res.ramTotalGb} GB · Swap {Math.round(res.swapUsedMb)} MB · Reserve {res.reserveGb} GB · Hauptstrang {Math.round(res.loopLagMs)} ms (max {Math.round(res.loopLagMaxMs)})
        </small>
      ) : null}
      {waiting.map((w) => (
        <small key={w.name}>
          Auftrag {String(w.waitingJob)} wartet auf Speicher ({w.needGb} GB, {INSTANCE_LABEL[w.name] ?? w.name})
        </small>
      ))}
    </div>
  );
}
