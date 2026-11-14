import { useState } from "react";
import { sendCommand } from "../core/commands";
import { ComfyState, JobResult, type ComfyStatus } from "../core/generated/darkfluenzer/v1/comfy_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useConnection } from "../core/realtime";
import { useEventTopic, useStateTopic, type StateValue } from "../core/state";

type Tone = "ok" | "warn" | "bad" | "neutral";

const STATE_LABEL: Record<ComfyState, [string, Tone]> = {
  [ComfyState.UNSPECIFIED]: ["UNBEKANNT", "neutral"],
  [ComfyState.STOPPED]: ["GESTOPPT", "neutral"],
  [ComfyState.STARTING]: ["STARTET", "warn"],
  [ComfyState.READY]: ["BEREIT", "ok"],
  [ComfyState.STOPPING]: ["STOPPT", "warn"],
  [ComfyState.UNREACHABLE]: ["NICHT ERREICHBAR", "bad"],
  [ComfyState.FAILED]: ["FEHLER", "bad"],
};

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("de-DE");
}

/** Zustand der ComfyUI-Instanz; veraltete Werte sind als solche gekennzeichnet. */
export function ComfyBadge({ comfy }: { comfy: StateValue<ComfyStatus> | undefined }) {
  if (!comfy) return <span className="g-badge">KEINE DATEN</span>;
  const [label, tone] = STATE_LABEL[comfy.value.state];
  const stale = comfy.staleSince !== null;
  return (
    <>
      {stale ? <small>veraltet seit {clock(comfy.staleSince!)}</small> : null}
      <span className="g-badge" data-tone={stale ? "stale" : tone}>
        {label}
      </span>
    </>
  );
}

export function ComfyUI() {
  const comfy = useStateTopic(Topic.COMFY_STATUS);
  const jobs = useEventTopic(Topic.JOB_COMPLETED);
  const connection = useConnection();
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");

  const s = comfy?.value;
  const usable = connection.status === "OPEN" && comfy?.staleSince === null && !pending;
  const showStart = s?.state === ComfyState.STOPPED || s?.state === ComfyState.FAILED;
  const showStop = s?.managed === true && (s.state === ComfyState.READY || s.state === ComfyState.UNREACHABLE);

  async function run(command: Parameters<typeof sendCommand>[0]) {
    setPending(true);
    setNotice("");
    try {
      const result = await sendCommand(command);
      if (!result.accepted) setNotice(result.detail);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="g-panel">
      <h1>ComfyUI</h1>
      <div className="g-section">
        <div className="g-line">
          <span>Instanz</span>
          <span className="g-value">
            <ComfyBadge comfy={comfy} />
          </span>
        </div>
        {s?.version ? (
          <div className="g-line">
            <span>Version</span>
            <span className="g-value">
              {s.version} · {s.device}
              {s.managed ? "" : " · nicht von Darkfluenzer gestartet"}
            </span>
          </div>
        ) : null}
        {s?.error ? (
          <p className="g-note" role="alert">
            {s.error}
          </p>
        ) : null}
        <div className="g-actions">
          {showStart ? (
            <button type="button" className="g-button g-primary" disabled={!usable} onClick={() => run({ case: "comfyStart", value: {} })}>
              Starten
            </button>
          ) : null}
          {showStop ? (
            <button type="button" className="g-button" disabled={!usable} onClick={() => run({ case: "comfyStop", value: {} })}>
              Stoppen
            </button>
          ) : null}
          {s?.state === ComfyState.READY && comfy?.staleSince === null ? (
            <a className="g-button" href={s.url} target="_blank" rel="noreferrer">
              ComfyUI öffnen
            </a>
          ) : null}
        </div>
        {notice ? (
          <p className="g-note" role="alert">
            {notice}
          </p>
        ) : null}
      </div>

      <div className="g-section">
        <h2>Ergebnisse</h2>
        {jobs?.gap ? <p className="g-note">Ältere Ergebnisse nicht nachgeladen.</p> : null}
        {jobs && jobs.items.length > 0 ? (
          [...jobs.items].reverse().map(({ cursor, committedMs, value: job }) => (
            <div className="g-line" key={String(cursor)}>
              <span>{job.workflow}</span>
              <span className="g-value">
                {clock(committedMs)} · {job.durationS.toFixed(1)} s · {job.outputs.length} Datei(en)
                <span className="g-badge" data-tone={job.result === JobResult.DONE ? "ok" : "bad"} title={job.error || undefined}>
                  {job.result === JobResult.DONE ? "FERTIG" : "FEHLER"}
                </span>
              </span>
            </div>
          ))
        ) : (
          <p className="g-note">
            {jobs?.live
              ? "Noch keine Renderung über Darkfluenzer."
              : connection.status === "OPEN"
                ? "Lädt …"
                : "Keine Verbindung"}
          </p>
        )}
      </div>
    </section>
  );
}
