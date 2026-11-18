import { type ActiveJob, JobResult, type MediaCheck, type WorkflowInfo } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { IMAGE, RESULT_BADGE, VIDEO, clock } from "./common";
import { JobParams, LoadDraft, Progress } from "./Queue";
import type { ReferenceItem } from "../../core/generated/darkfluenzer/v1/reference_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { fetchReferences, mediaUrl } from "../../core/media";
import { useEffect, useMemo, useRef, useState } from "react";
import { useEventTopic } from "../../core/state";

const RECENT_RESULTS = 4;

/** Ergebnis (Mitte): laufender Auftrag und die letzten echten Ausgaben dieses Workflows. */
/** Messwerte der Prüfknoten (SP3 Schritt 7); entschieden wird im Backend gegen die Schwellen. */
const CHECK_STATUS: Record<string, string> = {
  kein_gesicht: "nicht prüfbar (kein ausreichend großes Gesicht)",
  keine_referenz: "keine Referenzfotos der Figur",
  kein_prompt: "kein Prompt",
  keine_haende: "keine Hände erkannt",
};

const CHECK_NAME: Record<string, string> = {
  identity: "Identität",
  content: "Inhalt",
  quality: "Technik",
  quality_score: "Qualität",
  prompt_fidelity: "Prompttreue",
  hands: "Hände",
  frames: "Frames",
  temporal: "Zeitlich",
};

/** Video: Werte der Frame-Stichprobe je Prüfung in einer Zeile (Spanne bzw. Anzahl je Stufe). */
function frameSummary(name: string, list: MediaCheck[]): string {
  const ok = list.filter((c) => c.status === "ok");
  const head = `${list.length} Frames`;
  const status = list[0]?.status ?? "";
  if (ok.length === 0) return `${head} · ${CHECK_STATUS[status] ?? status}`;
  const span = (key: string, digits: number) => {
    const v = ok.map((c) => c.values[key] ?? 0);
    return `${Math.min(...v).toFixed(digits)}–${Math.max(...v).toFixed(digits)}`;
  };
  if (name === "content") {
    const counts = new Map<string, number>();
    for (const c of ok) counts.set(c.labels.rating ?? "", (counts.get(c.labels.rating ?? "") ?? 0) + 1);
    return [head, ...[...counts].map(([rating, n]) => `${rating} ×${n}`)].join(" · ");
  }
  if (name === "hands") return `${head} · ${ok.length} mit Händen · zählbar min ${span("countable_min", 2).split("–")[0]}`;
  if (name === "quality") return `${head} · Schärfe ${span("sharpness", 0)}`;
  if (name === "identity") return `${head} · SFace ${span("sface", 3)}`;
  return head;
}

/** Zeilen der Prüfwerte eines Auftrags; bei Video (Frame-Stichprobe) eine Zeile je Prüfung. */
function checkLines(checks: MediaCheck[]): { name: string; text: string }[] {
  if (!checks.some((c) => c.check === "frames")) return checks.map((c) => ({ name: c.check, text: checkText(c) }));
  const groups = new Map<string, MediaCheck[]>();
  for (const c of checks) groups.set(c.check, [...(groups.get(c.check) ?? []), c]);
  const sampled = Math.max(0, ...[...groups].filter(([n]) => n !== "frames").map(([, list]) => list.length));
  return [...groups].map(([name, [first, ...rest]]) => {
    if (name === "frames" && first) return { name, text: `${first.values.count ?? sampled} von ${first.values.total ?? 0} geprüft` };
    return { name, text: rest.length > 0 || !first ? frameSummary(name, first ? [first, ...rest] : []) : checkText(first) };
  });
}

/** Kurztext eines Messwerts; Schwellen und Entscheidung liegen im Backend (SP5 Schritt 7). */
function checkText(c: MediaCheck): string {
  if (c.status !== "ok") return CHECK_STATUS[c.status] ?? c.status;
  if (c.check === "identity") return `SFace ${c.sface.toFixed(3)} · AuraFace ${c.auraface.toFixed(3)} · ${c.references} Referenzen`;
  if (c.check === "content") {
    const rating = c.labels.rating ?? "";
    const exposed = Object.entries(c.values)
      .filter(([k]) => k.startsWith("regions.") && k.endsWith("_EXPOSED"))
      .map(([k, v]) => `${k.slice(8)} ${v.toFixed(2)}`);
    return [`${rating} ${(c.values[rating] ?? 0).toFixed(2)}`, ...exposed].join(" · ");
  }
  if (c.check === "hands") {
    return `${c.values.hands ?? 0} erkannt · zählbar min ${(c.values.countable_min ?? 0).toFixed(2)}`;
  }
  if (c.check === "prompt_fidelity") {
    const parts = c.values.parts ?? 1;
    return `VQAScore ${(c.values.score ?? 0).toFixed(2)}${parts > 1 ? ` · min ${(c.values.min ?? 0).toFixed(2)} · ${parts} Teile` : ""}`;
  }
  if (c.check === "quality_score") {
    const parts = [`Q-ReAlign ${(c.values.quality ?? 0).toFixed(2)}`];
    if (c.values.aesthetics !== undefined) parts.push(`Ästhetik ${c.values.aesthetics.toFixed(2)}`);
    return parts.join(" · ");
  }
  if (c.check === "quality") {
    const v = c.values;
    return `Schärfe ${(v.sharpness ?? 0).toFixed(0)} · Rauschen ${(v.noise ?? 0).toFixed(2)} · Kontrast ${(v.contrast ?? 0).toFixed(0)}`;
  }
  if (c.check === "temporal") {
    const v = c.values;
    return `Sprünge ${v.jumps ?? 0} · Standbilder ${v.frozen ?? 0} · Änderung Ø ${(v.mean_diff ?? 0).toFixed(1)} · Flackern ${(v.luma_flicker ?? 0).toFixed(2)}`;
  }
  return Object.entries(c.values)
    .map(([k, v]) => `${k} ${v.toFixed(3)}`)
    .join(" · ");
}

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
    .filter((e) => e.value.result !== JobResult.DONE || e.value.checks.length > 0 || e.value.outputs.some((o) => !gone.has(o.path)))
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
                {job.checks.length > 0 ? (
                  // Prüfwerte eingeklappt (GUI-Prüfung 18.11. Punkt 6): Kopf nennt die Prüfungen
                  <details className="g-checks">
                    <summary>
                      Prüfwerte · {[...new Set(checkLines(job.checks).map((c) => CHECK_NAME[c.name] ?? c.name))].join(", ")}
                    </summary>
                    {checkLines(job.checks).map((c, i) => (
                      <small key={i} className="g-line">
                        <span>{CHECK_NAME[c.name] ?? c.name}</span>
                        <span className="g-value">{c.text}</span>
                      </small>
                    ))}
                  </details>
                ) : null}
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
