import { type ActiveJob, JobResult, type WorkflowInfo } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { IMAGE, RESULT_BADGE, VIDEO, clock } from "./common";
import { JobParams, LoadDraft, Progress } from "./Queue";
import type { ReferenceItem } from "../../core/generated/darkfluenzer/v1/reference_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { fetchReferences, mediaUrl } from "../../core/media";
import { useEffect, useMemo, useRef, useState } from "react";
import { useEventTopic } from "../../core/state";

const RECENT_RESULTS = 4;

/** Ergebnis (Mitte): laufender Auftrag und die letzten echten Ausgaben dieses Workflows. */
export function WorkflowResults({
  wf,
  running,
  waiting,
  onLoad,
  canLoad,
}: {
  wf: WorkflowInfo;
  running: ActiveJob | undefined;
  waiting: number;
  onLoad: LoadDraft;
  canLoad: (key: string) => boolean;
}) {
  const results = useEventTopic(Topic.JOB_COMPLETED);
  const removed = useEventTopic(Topic.MEDIA_REMOVED);
  const gone = useMemo(() => new Set(removed?.items.map((e) => e.value.path)), [removed]);
  const [open, setOpen] = useState<bigint | null>(null);
  // nur echte Ergebnisse: vorhandene Ausgabedatei oder ein Fehler mit Grund (gelöschte Dateien entfallen)
  const recent = (results?.items ?? [])
    .filter((e) => e.value.workflow === wf.key)
    .filter((e) => e.value.result !== JobResult.DONE || e.value.outputs.some((o) => !gone.has(o.path)))
    .slice(-RECENT_RESULTS)
    .reverse();
  return (
    <div className="g-result">
      <div className="g-line g-head">
        <h2>Ergebnis</h2>
        <span className="g-value">
          {running ? (
            <>
              <small>Auftrag {String(running.jobId)}</small>
              <Progress job={running} />
            </>
          ) : null}
          {waiting ? <small>{waiting} wartend</small> : null}
        </span>
      </div>
      {results?.gap ? <p className="g-note">Ältere Ergebnisse nicht nachgeladen.</p> : null}
      {recent.length > 0 ? (
        <div className="g-results">
          {recent.map(({ cursor, committedMs, value: job }) => {
            const [label, tone] = RESULT_BADGE[job.result];
            const outs = job.outputs.filter((o) => !gone.has(o.path));
            const isOpen = open === cursor;
            return (
              <div className="g-tile" key={String(cursor)}>
                {outs.length > 0 ? (
                  <div className="g-tile-outputs">
                    {outs.map((out) =>
                      VIDEO.test(out.path) ? (
                        <video key={out.path} src={mediaUrl(out.path)} controls muted preload="metadata" />
                      ) : IMAGE.test(out.path) ? (
                        <a key={out.path} href={mediaUrl(out.path)} target="_blank" rel="noreferrer">
                          <img src={mediaUrl(out.path)} alt={`Auftrag ${job.jobId}`} loading="lazy" />
                        </a>
                      ) : null,
                    )}
                  </div>
                ) : null}
                <button
                  type="button"
                  className="g-row g-line"
                  aria-expanded={isOpen}
                  title={clock(committedMs)}
                  onClick={() => setOpen(isOpen ? null : cursor)}
                >
                  <span className="g-ellipsis">Auftrag {String(job.jobId)}</span>
                  <span className="g-badge" data-tone={tone}>
                    {label}
                  </span>
                </button>
                {job.result === JobResult.FAILED && job.error ? <p className="g-note g-error">{job.error}</p> : null}
                {outs
                  .filter((o) => !VIDEO.test(o.path) && !IMAGE.test(o.path))
                  .map((o) => (
                    <small key={o.path} className="g-ellipsis" title={`local/${o.path}`}>
                      {o.path.split("/").pop()}
                    </small>
                  ))}
                {isOpen ? (
                  <div className="g-details">
                    <JobParams workflow={job.workflow} params={job.params} />
                    {canLoad(job.workflow) ? (
                      <div className="g-actions">
                        <button type="button" className="g-button" onClick={() => onLoad(job.workflow, job.params)}>
                          In Formular laden
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="g-note">Ergebnisse erscheinen hier nach dem Rendern.</p>
      )}
    </div>
  );
}

/** Vorlagenbibliothek (C1): Vorlagen aus Dateien und dem Kloner-Eingang, bei Aufruf geladen. */
export function ReferencePicker({ onPick, onClose }: { onPick: (ref: ReferenceItem) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [items, setItems] = useState<ReferenceItem[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    fetchReferences()
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  return (
    <dialog ref={dialog} className="g-dialog g-media" aria-labelledby="ref-pick" onClose={onClose}>
      <div className="g-line g-head">
        <h2 id="ref-pick">Vorlage wählen</h2>
        <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
          Schließen
        </button>
      </div>
      {items && items.length > 0 ? (
        <div className="g-gallery">
          {items.map((r) => (
            <div key={String(r.referenceId)} className="g-tile">
              <button
                type="button"
                className="g-tile-open"
                title={`local/${r.path}`}
                onClick={() => {
                  onPick(r);
                  dialog.current?.close();
                }}
              >
                <img src={mediaUrl(r.path)} alt={`Vorlage ${String(r.referenceId)}`} />
                <small>{r.source}</small>
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="g-note">{error || (items ? "Noch keine Vorlagen – „Als Vorlage“ in Dateien oder Kloner-Eingang." : "Lädt …")}</p>
      )}
    </dialog>
  );
}
