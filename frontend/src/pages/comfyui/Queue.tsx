import type { ActiveJob } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { LABEL, duration } from "./common";

/** Vorrangklasse je Job (SP5 Schritt 5); Reihenfolge laut Backend-Konfiguration. */
const PRIORITY_LABEL: Record<string, string> = { customer: "Kunde", default: "Default", cockpit: "Cockpit", training: "Training" };
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useCommand } from "../../core/commands";
import { useState } from "react";
import { useStateTopic } from "../../core/state";

/** Laufender Auftrag: Balken mit Schritten, sobald ComfyUI Fortschritt meldet. */
export function Progress({ job }: { job: ActiveJob }) {
  if (!job.progressMax) return <small>läuft</small>;
  return (
    <>
      <progress className="g-progress" value={job.progressValue} max={job.progressMax} />
      <small>
        {job.progressValue}/{job.progressMax}
      </small>
    </>
  );
}

export type LoadDraft = (workflow: string, params: Record<string, string>) => void;

const FIRST_PARAMS = ["prompt", "negative_prompt"];

const FILE_PARAMS = new Set(["image", "mask"]);

/** Parameter eines Auftrags zum Nachsehen; Eingabedateien mit ihrem Namen. */
export function JobParams({ workflow, params }: { workflow: string; params: Record<string, string> }) {
  const declared = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows.find((w) => w.key === workflow)?.params;
  const label = (n: string) => declared?.find((p) => p.name === n)?.label || (n === "prompt" ? "Prompt" : n === "image" ? "Bild" : (LABEL[n] ?? n));
  const names = [
    ...FIRST_PARAMS.filter((n) => n in params),
    ...Object.keys(params)
      .filter((n) => !FIRST_PARAMS.includes(n))
      .sort(),
  ];
  return (
    <dl className="g-params">
      {names.map((n) => (
        <div key={n}>
          <dt>{label(n)}</dt>
          <dd>{FILE_PARAMS.has(n) ? params[n]!.split("/").pop() : params[n]}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Queue({ instance, onLoad, canLoad }: { instance: string; onLoad: LoadDraft; canLoad: (key: string) => boolean }) {
  const active = useStateTopic(Topic.JOBS_ACTIVE)?.value;
  const jobs = (active?.jobs ?? []).filter((j) => j.instance === instance);
  const paused = active?.paused.includes(instance) ?? false;
  const cmd = useCommand();
  const [open, setOpen] = useState<bigint | null>(null);
  return (
    <div className="g-control-part">
      <div className="g-line g-head">
        <h2>Warteschlange</h2>
        <span className="g-value">
          {paused ? (
            <span className="g-badge" data-tone="warn">
              ANGEHALTEN
            </span>
          ) : null}
          <button
            type="button"
            className="g-button"
            disabled={!active || cmd.pending}
            onClick={() => cmd.run({ case: "pauseQueue", value: { paused: !paused, instance } })}
          >
            {paused ? "Fortsetzen" : "Anhalten"}
          </button>
        </span>
      </div>
      {jobs.length > 0 ? (
        jobs.map((job, i) => {
          const isOpen = job.jobId !== 0n && open === job.jobId;
          return (
            <div className="g-qitem" key={`${job.jobId}-${i}`}>
              <button
                type="button"
                className="g-line g-row"
                aria-expanded={job.jobId ? isOpen : undefined}
                disabled={!job.jobId}
                onClick={() => setOpen(isOpen ? null : job.jobId)}
              >
                <span className="g-ellipsis">
                  {i + 1}. {job.jobId ? job.workflow : "Auftrag aus der ComfyUI-Oberfläche"}
                  {job.priority ? <small> · {PRIORITY_LABEL[job.priority] ?? job.priority}</small> : null}
                </span>
                {job.running ? (
                  <span className="g-badge" data-tone={job.unknown ? "warn" : "ok"}>
                    {job.unknown ? "UNBEKANNT" : "LÄUFT"}
                  </span>
                ) : (
                  <span className="g-value">wartet{job.estimateS ? ` · ~${duration(job.estimateS)}` : ""}</span>
                )}
              </button>
              {job.running && job.progressMax ? (
                <div className="g-qprogress">
                  <Progress job={job} />
                </div>
              ) : null}
              {job.running && job.remainingS ? (
                <small className="g-note">
                  läuft seit {duration(job.elapsedS)} · noch ~{duration(job.remainingS)} (Schätzung)
                </small>
              ) : null}
              {job.unknown ? (
                <p className="g-note" role="status">
                  Zustand unbekannt: ComfyUI antwortet nicht. Abgleich nach der Wiederverbindung, kein automatischer Neustart.
                </p>
              ) : null}
              {job.stalledS ? (
                <p className="g-note" role="status">
                  Seit {duration(job.stalledS)} kein Fortschritt. Der Lauf geht weiter.
                </p>
              ) : null}
              {isOpen ? (
                <div className="g-details">
                  <JobParams workflow={job.workflow} params={job.params} />
                  <div className="g-actions">
                    <button
                      type="button"
                      className="g-button g-danger"
                      disabled={cmd.pending}
                      onClick={() => cmd.run({ case: "cancelJob", value: { jobId: job.jobId } })}
                    >
                      {job.running ? "Abbrechen" : "Entfernen"}
                    </button>
                    {canLoad(job.workflow) ? (
                      <button type="button" className="g-button" onClick={() => onLoad(job.workflow, job.params)}>
                        In Formular laden
                      </button>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          );
        })
      ) : (
        <p className="g-note">Leer</p>
      )}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}
