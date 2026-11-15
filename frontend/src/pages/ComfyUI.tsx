import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useCommand } from "../core/commands";
import {
  ComfyState,
  JobResult,
  type ActiveJob,
  type ComfyStatus,
  type WorkflowInfo,
  type WorkflowParam,
} from "../core/generated/darkfluenzer/v1/comfy_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { takeRenderIntent, type RenderIntent } from "../core/intent";
import { fetchReferences, mediaUrl } from "../core/media";
import { type ReferenceItem } from "../core/generated/darkfluenzer/v1/reference_pb";
import { useConnection } from "../core/realtime";
import { type MediaItem } from "../core/generated/darkfluenzer/v1/media_pb";
import { type Character } from "../core/generated/darkfluenzer/v1/character_pb";
import { type ActiveOrder } from "../core/generated/darkfluenzer/v1/order_pb";
import { useEventTopic, useStateTopic } from "../core/state";
import { MediaPicker } from "./Files";

type Tone = "ok" | "warn" | "bad" | "neutral";
type Kind = "image" | "video" | "ai";

const STATE_LABEL: Record<ComfyState, [string, Tone]> = {
  [ComfyState.UNSPECIFIED]: ["UNBEKANNT", "neutral"],
  [ComfyState.STOPPED]: ["GESTOPPT", "neutral"],
  [ComfyState.STARTING]: ["STARTET", "warn"],
  [ComfyState.READY]: ["BEREIT", "ok"],
  [ComfyState.BUSY]: ["ARBEITET", "ok"],
  [ComfyState.STOPPING]: ["STOPPT", "warn"],
  [ComfyState.UNREACHABLE]: ["NICHT ERREICHBAR", "bad"],
  [ComfyState.FAILED]: ["FEHLER", "bad"],
};

const WORKFLOW_TONE: Record<string, Tone> = { PASS: "ok", OFFEN: "neutral", GESPERRT: "bad" };
const KINDS: readonly [Kind, string][] = [
  ["image", "Fotos"],
  ["video", "Videos"],
  ["ai", "KI"],
];
/** Unterregister eines Workflows: KI-Instanz (ComfyUI 2) bzw. Foto/Video der Medieninstanz. */
function tabOf(w: WorkflowInfo): Kind {
  return w.instance === "ai" ? "ai" : (w.kind as Kind);
}
const LABEL: Record<string, string> = {
  negative_prompt: "Negativ-Prompt",
  seed: "Seed",
  steps: "Schritte",
  cfg: "CFG",
  width: "Breite",
  height: "Höhe",
  denoise: "Stärke",
  mask_grow: "Maskenrand (px)",
  mask: "Maske",
};
const IMAGE = /\.(png|jpe?g|webp)$/i;

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("de-DE");
}

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

const INSTANCE_LABEL: Record<string, string> = { media: "ComfyUI 1 · Medien", ai: "ComfyUI 2 · KI" };

/** URL einer bereiten Instanz (für „Öffnen“ im Editor), sonst leer. */
function readyUrl(s: ComfyStatus | undefined, live: boolean): string {
  return live && (s?.state === ComfyState.READY || s?.state === ComfyState.BUSY) ? s.url : "";
}

/** Ein Befehl mit sichtbarem Ergebnis: läuft, Ablehnungsgrund oder Fehler. */
function paramLabel(p: WorkflowParam, kind: string): string {
  if (p.label) return p.label; // Feldname aus der Registry
  if (p.name === "prompt") return kind === "video" ? "Szene und Bewegung" : "Motiv, Komposition, Perspektive, Licht";
  if (p.name === "image") return kind === "video" ? "Startbild" : "Quellbild";
  return LABEL[p.name] ?? p.name;
}

function defaultText(p: WorkflowParam): string {
  return p.default.case === undefined ? "" : String(p.default.value);
}

function validate(p: WorkflowParam, raw: string, chosen: boolean): string {
  if (p.upload) return p.required && !chosen ? "Datei wählen" : "";
  if (raw.trim() === "") return "Darf nicht leer sein";
  if (p.choices.length > 0) return p.choices.includes(raw) ? "" : "Ungültige Auswahl";
  if (p.type === "str") return "";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "Zahl erwartet";
  if (p.type === "int" && !Number.isInteger(n)) return "Ganzzahl erwartet";
  if (p.min !== undefined && n < p.min) return `Mindestens ${p.min}`;
  if (p.max !== undefined && n > p.max) return `Höchstens ${p.max}`;
  if (p.multipleOf && n % p.multipleOf !== 0) return `Vielfaches von ${p.multipleOf}`;
  return "";
}

/** Laufender Auftrag: Balken mit Schritten, sobald ComfyUI Fortschritt meldet. */
function Progress({ job }: { job: ActiveJob }) {
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
function Instances({ live }: { live: boolean }) {
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
          Speicher frei {res.ramFreeGb} von {res.ramTotalGb} GB · Swap {Math.round(res.swapUsedMb)} MB · Reserve {res.reserveGb} GB
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

type LoadDraft = (workflow: string, params: Record<string, string>) => void;
const FIRST_PARAMS = ["prompt", "negative_prompt"];
const FILE_PARAMS = new Set(["image", "mask"]);

/** Parameter eines Auftrags zum Nachsehen; Eingabedateien mit ihrem Namen. */
function JobParams({ workflow, params }: { workflow: string; params: Record<string, string> }) {
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

function Queue({ instance, onLoad, canLoad }: { instance: string; onLoad: LoadDraft; canLoad: (key: string) => boolean }) {
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
                </span>
                {job.running ? (
                  <span className="g-badge" data-tone="ok">
                    LÄUFT
                  </span>
                ) : (
                  <span className="g-value">wartet</span>
                )}
              </button>
              {job.running && job.progressMax ? (
                <div className="g-qprogress">
                  <Progress job={job} />
                </div>
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

const RESULT_BADGE: Record<JobResult, [string, Tone]> = {
  [JobResult.UNSPECIFIED]: ["UNBEKANNT", "neutral"],
  [JobResult.DONE]: ["FERTIG", "ok"],
  [JobResult.FAILED]: ["FEHLER", "bad"],
  [JobResult.CANCELLED]: ["ABGEBROCHEN", "neutral"],
};
const VIDEO = /\.(mp4|webm|mov)$/i;
const RECENT_RESULTS = 4;

/** Ergebnis (Mitte): laufender Auftrag und die letzten echten Ausgaben dieses Workflows. */
function WorkflowResults({
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

const PHOTO_STATUS: Record<string, string> = {
  incomplete: "wird kopiert",
  unsupported: "Format",
  unreadable: "nicht lesbar",
  duplicate: "doppelt",
  too_small: "zu klein",
};

/** Vorlagenbibliothek (C1): Vorlagen aus Dateien und dem Kloner-Eingang, bei Aufruf geladen. */
function ReferencePicker({ onPick, onClose }: { onPick: (ref: ReferenceItem) => void; onClose: () => void }) {
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

// Gewähltes Charakterprofil (F7.5 „Charakter“); bleibt beim Wechsel des Workflows erhalten.
let chosenCharacter = "";

function useCharacter() {
  const list = useStateTopic(Topic.CHARACTERS)?.value.characters ?? [];
  const [id, setId] = useState(chosenCharacter);
  const current = list.find((c) => c.id === id) ?? list[0];
  function choose(next: string) {
    chosenCharacter = next;
    setId(next);
  }
  return { list, current, choose };
}

/** Charakter (Steuerung, F7.5): Profil wählen, anlegen, umbenennen; bei Trainingsworkflows den
 *  Trainingsdatenordner übernehmen (Befehl 25, CAS über die Profilrevision). */
function CharacterControl({ training, list, current, choose }: { training: boolean } & ReturnType<typeof useCharacter>) {
  const cmd = useCommand();
  const [editing, setEditing] = useState<"" | "new" | "edit">("");
  const [name, setName] = useState("");
  const [path, setPath] = useState(current?.photosDir ?? "");
  useEffect(() => setPath(current?.photosDir ?? ""), [current?.id, current?.photosDir]);

  async function save(e: FormEvent) {
    e.preventDefault();
    const create = editing === "new";
    const done = await cmd.run(
      {
        case: "characterUpdate",
        value: {
          characterId: create || !current ? 0n : BigInt(current.id),
          revision: create || !current ? 0n : current.revision,
          name: name.trim(),
          photosDir: create ? "" : (current?.photosDir ?? ""),
        },
      },
      { done: create ? "Charakter angelegt." : "Name übernommen." },
    );
    if (done) setEditing("");
  }

  async function takePath() {
    if (!current) return;
    await cmd.run(
      {
        case: "characterUpdate",
        value: { characterId: BigInt(current.id), revision: current.revision, name: current.name, photosDir: path.trim() },
      },
      { done: "Pfad übernommen." },
    );
  }

  return (
    <>
      <div className="g-field">
        <label htmlFor="cf-character">Charakter</label>
        <span className="g-between">
          <select
            id="cf-character"
            className="g-input"
            value={editing === "new" ? "new" : (current?.id ?? "")}
            onChange={(e) => {
              if (e.target.value === "new") {
                setName("");
                setEditing("new");
              } else {
                setEditing("");
                choose(e.target.value);
              }
            }}
          >
            {list.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
            <option value="new">Neuer Charakter …</option>
          </select>
          {current && editing === "" ? (
            <button
              type="button"
              className="g-button"
              onClick={() => {
                setName(current.name);
                setEditing("edit");
              }}
            >
              Bearbeiten
            </button>
          ) : null}
        </span>
      </div>
      {editing ? (
        <form className="g-actions" onSubmit={save}>
          <input
            className="g-input"
            aria-label="Name des Charakters"
            placeholder="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="g-button g-primary" disabled={cmd.pending || !name.trim()}>
            {editing === "new" ? "Anlegen" : "Übernehmen"}
          </button>
          <button type="button" className="g-button" onClick={() => setEditing("")}>
            Abbrechen
          </button>
        </form>
      ) : null}
      {training && current ? (
        <div className="g-field">
          <label htmlFor="cf-trainpath">Trainingsdatenordner</label>
          <input id="cf-trainpath" className="g-input g-mono" value={path} onChange={(e) => setPath(e.target.value)} />
          <span className="g-between">
            <button type="button" className="g-button" disabled={cmd.pending || !path.trim() || path.trim() === current.photosDir} onClick={() => void takePath()}>
              Pfad übernehmen
            </button>
            <small>Alle geeigneten Bilder</small>
          </span>
          {current.photosMissing ? <small className="g-error">Ordner existiert nicht.</small> : null}
        </div>
      ) : null}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </>
  );
}

/** Charaktertraining (Mitte, F7): geprüfter Inhalt des Trainingsdatenordners, Datensätze, LoRAs. */
function TrainingFolder({ character }: { character: Character | undefined }) {
  if (!character) return <p className="g-note">Keine Daten zum Trainingsordner.</p>;
  const problems = character.photos.filter((p) => p.status !== "ok");
  return (
    <div className="g-training">
      <h3>Charaktertraining</h3>
      <p className="g-note">Alle geeigneten Bilder aus dem Trainingsordner werden automatisch als Datensatz verwendet.</p>
      <div className="g-line">
        <span>Geeignete Bilder</span>
        <span className="g-value">
          {character.usable} von {character.photos.length} · mindestens {character.minImages}
        </span>
      </div>
      {problems.map((p) => (
        <small key={p.name} className="g-line">
          <span className="g-ellipsis">{p.name}</span>
          <span className="g-value">{[PHOTO_STATUS[p.status] ?? p.status, p.note].filter(Boolean).join(" · ")}</span>
        </small>
      ))}
      {character.datasets[0] ? (
        <div className="g-line">
          <span>Datensatz</span>
          <span className="g-value">
            {character.datasets[0].id} · {character.datasets[0].images} Bilder
          </span>
        </div>
      ) : null}
      {character.loras.map((l) => (
        <div className="g-line" key={l.key}>
          <span className="g-ellipsis">{l.key}</span>
          <span className="g-badge" data-tone={WORKFLOW_TONE[l.status] ?? "neutral"}>
            {l.status}
          </span>
        </div>
      ))}
    </div>
  );
}

const STAGE_LABEL: Record<string, [string, Tone]> = {
  running: ["LÄUFT", "ok"],
  waiting: ["AUSWAHL", "warn"],
  done: ["FERTIG", "ok"],
  failed: ["FEHLER", "bad"],
  cancelled: ["ABGEBROCHEN", "neutral"],
};

/** Kandidatenvergleich (Mitte, V0 §9.6): je Kandidat ein echtes Ergebnis, synchroner Zoom,
 * Auswahl durch den Betreiber; danach Fertigstellen. */
export function Candidates({
  orders,
  titles,
  heading = true,
}: {
  orders: ActiveOrder[];
  titles: Record<string, string>;
  heading?: boolean;
}) {
  const cmd = useCommand();
  const jobs = useStateTopic(Topic.JOBS_ACTIVE)?.value.jobs ?? [];
  const [zoom, setZoom] = useState<{ x: number; y: number } | null>(null);
  if (orders.length === 0) return null;
  return (
    <div className="g-result">
      {heading ? <h2>Kandidaten</h2> : null}
      {orders.map((order) => (
        <div key={order.orderNo} className="g-order">
          {order.stages.map((stage) => {
            const [label, tone] = STAGE_LABEL[stage.status] ?? [stage.status, "neutral"];
            const failed = stage.jobs.some((j) => j.status === "failed");
            return (
              <div key={stage.seq} className="g-stage">
                <div className="g-line">
                  <span className="g-ellipsis">
                    {order.orderNo} · {stage.kind === "finish" ? `Fertigstellen · ${titles[stage.workflow] ?? stage.workflow}` : "Kandidaten"}
                  </span>
                  <span className="g-value">
                    {stage.attempts > 1 ? <small>Versuch {stage.attempts}</small> : null}
                    <span className="g-badge" data-tone={tone}>
                      {label}
                    </span>
                  </span>
                </div>
                {stage.error && stage.status === "failed" ? <p className="g-note g-error">{stage.error}</p> : null}
                <div
                  className="g-candidates"
                  data-zoom={zoom ? "" : undefined}
                  data-zx={zoom ? zoom.x : undefined}
                  data-zy={zoom ? zoom.y : undefined}
                >
                  {stage.jobs.map((j) => {
                    const active = jobs.find((a) => a.jobId === j.jobId);
                    const chosen = stage.selectedMediaId !== 0n && stage.selectedMediaId === j.mediaId;
                    return (
                      <div key={String(j.jobId)} className="g-candidate" data-chosen={chosen ? "" : undefined}>
                        {j.mediaId && IMAGE.test(j.path) ? (
                          <div
                            className="g-zoom"
                            onMouseMove={(e) => {
                              const r = e.currentTarget.getBoundingClientRect();
                              // Zoompunkt in Zehnerschritten (Stufen im Stylesheet)
                              const step = (v: number) => Math.min(10, Math.max(0, Math.round(v * 10)));
                              setZoom({ x: step((e.clientX - r.left) / r.width), y: step((e.clientY - r.top) / r.height) });
                            }}
                            onMouseLeave={() => setZoom(null)}
                          >
                            <img src={mediaUrl(j.path)} alt={`Kandidat Seed ${j.seed}`} />
                          </div>
                        ) : j.mediaId && VIDEO.test(j.path) ? (
                          <video src={mediaUrl(j.path)} controls muted preload="metadata" />
                        ) : (
                          <div className="g-placeholder">
                            {j.status === "failed" ? "Fehler" : active?.running ? <Progress job={active} /> : "wartet"}
                          </div>
                        )}
                        <div className="g-line">
                          <small>Seed {String(j.seed)}</small>
                          {stage.status === "waiting" && j.mediaId ? (
                            <button
                              type="button"
                              className="g-button g-primary"
                              disabled={cmd.pending}
                              onClick={() => cmd.run({ case: "selectCandidate", value: { orderNo: order.orderNo, mediaId: j.mediaId } })}
                            >
                              Auswählen
                            </button>
                          ) : chosen ? (
                            <span className="g-badge" data-tone="ok">
                              AUSGEWÄHLT
                            </span>
                          ) : null}
                        </div>
                        {j.status === "failed" && j.error ? <small className="g-error">{j.error}</small> : null}
                      </div>
                    );
                  })}
                </div>
                {failed && (stage.status === "failed" || stage.status === "waiting") ? (
                  <div className="g-actions">
                    <button
                      type="button"
                      className="g-button"
                      disabled={cmd.pending}
                      onClick={() => cmd.run({ case: "retryStage", value: { orderNo: order.orderNo, seq: stage.seq } })}
                    >
                      Fehlgeschlagene wiederholen
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ))}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

/** Arbeitsfläche (Mitte) und Steuerung (rechts) des gewählten Workflows (F7.5). */
function Workbench({
  wf,
  workflows,
  version,
  live,
  comfyUrl,
  draft,
  start,
  startParam,
  onLoad,
  canLoad,
}: {
  wf: WorkflowInfo;
  workflows: WorkflowInfo[]; // Registry (Fertigstellen-Auswahl)
  version: bigint; // Registry-Version (CAS) der angezeigten Workflow-Liste
  live: boolean;
  comfyUrl: string;
  draft?: Record<string, string>;
  start?: MediaItem; // aus Dateien übernommenes Eingabebild (Weiterverarbeiten, Video erstellen)
  startParam?: string; // Eingang dafür (Standard „image“, „Als Vorlage“: Vorlagen-Parameter)
  onLoad: LoadDraft;
  canLoad: (key: string) => boolean;
}) {
  const cmd = useCommand();
  const chars = useCharacter();
  const character = chars.current;
  const ordersState = useStateTopic(Topic.ORDERS_ACTIVE)?.value;
  const myOrders = (ordersState?.orders ?? []).filter((o) => o.stages[0]?.workflow === wf.key);
  // Kandidaten nur mit Seed (Varianten) und nicht beim Training; Fertigstellen: Bild-Workflows,
  // die außer dem Bild nichts verlangen, auf derselben Instanz
  const canCandidates = !wf.training && wf.params.some((p) => p.name === "seed");
  const finishers = workflows.filter(
    (w) =>
      w.key !== wf.key &&
      w.kind === "image" &&
      w.instance === wf.instance &&
      !w.training &&
      w.params.some((p) => p.name === "image" && p.upload) &&
      w.params.every((p) => !p.required || p.name === "image"),
  );
  const [count, setCount] = useState("");
  const [finish, setFinish] = useState("");
  const candidates = count === "" ? (ordersState?.candidatesDefault ?? 1) : Number(count);
  const titles = Object.fromEntries(workflows.map((w) => [w.key, w.title]));
  const mine = (useStateTopic(Topic.JOBS_ACTIVE)?.value.jobs ?? []).filter((j) => j.workflow === wf.key);
  const running = mine.find((j) => j.running);
  const waiting = mine.filter((j) => !j.running).length;
  const dialog = useRef<HTMLDialogElement>(null);
  const [raw, setRaw] = useState<Record<string, string>>(() =>
    Object.fromEntries(wf.params.filter((p) => !p.upload).map((p) => [p.name, draft?.[p.name] ?? defaultText(p)])),
  );
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (draft) top.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [draft]);
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  // Eingabebild aus der Galerie: exakt dieses Medium über seine ID (Backend prüft den SHA-256)
  const [picked, setPicked] = useState<Record<string, MediaItem | undefined>>(() => (start ? { [startParam ?? "image"]: start } : {}));
  const [picking, setPicking] = useState<WorkflowParam | null>(null);
  // Vorlage aus der Bibliothek (C1): exakt diese Datei über ihre ID (Backend prüft den SHA-256)
  const [pickedRef, setPickedRef] = useState<Record<string, ReferenceItem | undefined>>({});
  const [refPicking, setRefPicking] = useState<WorkflowParam | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const [checked, setChecked] = useState(false);
  const format = wf.formats.find((f) => String(f.width) === raw.width && String(f.height) === raw.height)?.name ?? "";
  const [expert, setExpert] = useState(false); // erweiterte Einstellungen: anfangs geschlossen
  // Mitte: Grundeinstellungen (Texte, Eingabebilder); rechts die Experten-Eingänge (F7.5, V0 §7)
  const inMain = (p: WorkflowParam) => !p.expert;
  const errors = Object.fromEntries(
    wf.params.map((p) => [p.name, validate(p, raw[p.name] ?? "", Boolean(files[p.name] || picked[p.name] || pickedRef[p.name]))]),
  );
  const blocked = !wf.enabled
    ? "Deaktiviert"
    : wf.status === "GESPERRT"
      ? "Gesperrt"
      : !wf.modelsReady
        ? `Modelle fehlen (${wf.missingGb.toFixed(1)} GB)`
        : wf.training && (!character || character.usable < character.minImages)
          ? `Zu wenige geeignete Bilder (${character?.usable ?? 0}/${character?.minImages ?? "?"})`
          : "";

  async function generate() {
    setChecked(true);
    if (Object.values(errors).some(Boolean)) {
      if (wf.params.some((p) => !inMain(p) && errors[p.name])) setExpert(true); // Fehler sichtbar machen
      return;
    }
    const values = wf.params
      .filter((p) => !p.upload)
      .map((p) => {
        const text = raw[p.name] ?? "";
        const value =
          p.type === "int"
            ? { case: "integer" as const, value: BigInt(text) }
            : p.type === "float"
              ? { case: "number" as const, value: Number(text) }
              : { case: "text" as const, value: text };
        return { name: p.name, value };
      });
    const inputs = await Promise.all(
      wf.params
        .filter((p) => p.upload && (files[p.name] || picked[p.name] || pickedRef[p.name]))
        .map(async (p) => {
          const ref = pickedRef[p.name];
          if (ref) return { param: p.name, filename: ref.path.split("/").pop() ?? "", referenceId: ref.referenceId };
          const item = picked[p.name];
          if (item) return { param: p.name, filename: item.path.split("/").pop() ?? "", mediaId: item.mediaId };
          const file = files[p.name]!;
          return { param: p.name, filename: file.name, data: new Uint8Array(await file.arrayBuffer()) };
        }),
    );
    const parentMediaId = picked.image?.mediaId ?? 0n;
    const asOrder = canCandidates && (candidates > 1 || finish !== "");
    const done = asOrder
      ? await cmd.run(
          {
            case: "createOrder",
            value: { workflow: wf.key, values, files: inputs, parentMediaId, candidates, finishWorkflow: finish },
          },
          { version, done: `${candidates} Kandidaten eingereiht.` },
        )
      : await cmd.run(
          {
            case: "render",
            value: { workflow: wf.key, values, files: inputs, parentMediaId, characterId: wf.training && character ? BigInt(character.id) : 0n },
          },
          { version, acceptedOnly: true, done: "Eingereiht." },
        );
    if (done) setChecked(false);
  }

  function pick(param: string, item: MediaItem) {
    const input = fileInputs.current[param];
    if (input) input.value = ""; // Galerie-Medium ersetzt eine lokal gewählte Datei
    setFiles((f) => ({ ...f, [param]: undefined }));
    setPicked((p) => ({ ...p, [param]: item }));
    setPickedRef((r) => ({ ...r, [param]: undefined }));
  }

  async function openInEditor() {
    // Tab sofort im Klick öffnen (sonst blockiert der Browser), Ziel erst nach Freigabe setzen.
    const tab = window.open("", "darkfluenzer-comfyui");
    if (await cmd.run({ case: "openWorkflow", value: { workflow: wf.key } }, { version })) {
      if (tab) tab.location.href = `${comfyUrl}/?workflows=${encodeURIComponent(wf.key)}`;
    } else {
      tab?.close();
    }
  }

  function field(p: WorkflowParam) {
    const id = `${wf.key}-${p.name}`;
    const error = checked ? errors[p.name] : "";
    const from = p.upload ? picked[p.name] : undefined;
    return (
      <div className={`g-field${p.type === "str" && !p.upload ? " g-wide" : ""}`} key={p.name}>
        <label htmlFor={id}>
          {paramLabel(p, wf.kind)}
          {p.required ? " *" : ""}
        </label>
        {p.upload ? (
          <div className="g-file">
            <input
              id={id}
              ref={(el) => {
                fileInputs.current[p.name] = el;
              }}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => {
                setFiles({ ...files, [p.name]: e.target.files?.[0] });
                setPicked({ ...picked, [p.name]: undefined });
              }}
            />
            <button type="button" className="g-button" onClick={() => setPicking(p)}>
              Aus Dateien
            </button>
          </div>
        ) : p.choices.length > 0 ? (
          <select id={id} value={raw[p.name]} onChange={(e) => setRaw({ ...raw, [p.name]: e.target.value })}>
            {p.choices.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        ) : p.type === "str" ? (
          <textarea id={id} rows={p.name === "prompt" ? 4 : 2} value={raw[p.name]} onChange={(e) => setRaw({ ...raw, [p.name]: e.target.value })} />
        ) : (
          <input
            id={id}
            type="number"
            min={p.min}
            max={p.max}
            step={p.type === "int" ? p.multipleOf || 1 : "any"}
            value={raw[p.name]}
            onChange={(e) => setRaw({ ...raw, [p.name]: e.target.value })}
          />
        )}
        {from ? (
          <span className="g-picked">
            <img className="g-thumb" src={mediaUrl(from.path)} alt={from.caption} />
            {from.caption} · local/{from.path}
          </span>
        ) : null}
        {error ? <small className="g-error">{error}</small> : null}
      </div>
    );
  }

  const expertParams = wf.params.filter((p) => !inMain(p));
  return (
    <>
      <div className="g-workmain" ref={top}>
        <h2>{wf.title}</h2>
        <small>{wf.engineTitle}</small>
        {draft ? (
          <p className="g-note">
            Aus einem Auftrag geladen{wf.params.some((p) => p.upload) ? " – Bilddateien neu wählen." : "."}
          </p>
        ) : null}
        {wf.training ? <TrainingFolder character={character} /> : null}
        <div className="g-form">
          {[...wf.params.filter((p) => inMain(p) && !p.upload), ...wf.params.filter((p) => p.upload && !p.reference)].map(field)}
        </div>
        <Candidates orders={myOrders} titles={titles} />
        <WorkflowResults wf={wf} running={running} waiting={waiting} onLoad={onLoad} canLoad={canLoad} />
      </div>

      <aside className="g-control" aria-label="Steuerung">
        <h2>Steuerung</h2>
        <div className="g-control-part">
          <CharacterControl training={wf.training} {...chars} />
          {wf.params
            .filter((p) => p.reference)
            .map((p) => {
              const chosen = pickedRef[p.name]?.path ?? picked[p.name]?.path;
              return (
                <div className="g-field" key={p.name}>
                  <label>
                    Vorlage{p.required ? " *" : ""}
                  </label>
                  {chosen ? (
                    <img className="g-thumb" src={mediaUrl(chosen)} alt="Gewählte Vorlage" />
                  ) : (
                    <small>Keine Vorlage gewählt</small>
                  )}
                  <span className="g-between">
                    <button type="button" className="g-button" onClick={() => setPicking(p)}>
                      Aus Dateien
                    </button>
                    <button type="button" className="g-button" onClick={() => setRefPicking(p)}>
                      Aus Vorlagen
                    </button>
                  </span>
                  {checked && errors[p.name] ? <small className="g-error">{errors[p.name]}</small> : null}
                </div>
              );
            })}
          <div className="g-line">
            <span>Workflow</span>
            <span className="g-value">
              <span className="g-ellipsis">{wf.title}</span>
              <span className="g-badge" data-tone={WORKFLOW_TONE[wf.status] ?? "neutral"}>
                {wf.status}
              </span>
            </span>
          </div>
          <small>
            {wf.modelsReady ? "Modelle bereit" : `fehlt ${wf.missingGb.toFixed(1)} GB`}
            {wf.usage === "production" ? "" : " · nur Evaluation"}
            {wf.editorChanged ? " · im Editor geändert" : ""}
          </small>
          <label className="g-switch">
            <input
              type="checkbox"
              role="switch"
              checked={wf.enabled}
              disabled={!live || cmd.pending}
              onChange={(e) =>
                cmd.run({ case: "setWorkflowEnabled", value: { workflow: wf.key, enabled: e.target.checked } }, { version })
              }
            />
            Aktiviert
          </label>
          <div className="g-actions">
            <button type="button" className="g-button" disabled={!live || !comfyUrl || cmd.pending} onClick={openInEditor}>
              Öffnen
            </button>
            {wf.editorChanged ? (
              <button
                type="button"
                className="g-button"
                disabled={!live || !comfyUrl || cmd.pending}
                onClick={() => cmd.run({ case: "adoptWorkflow", value: { workflow: wf.key } }, { version, done: "Übernommen." })}
              >
                Änderung übernehmen
              </button>
            ) : null}
            <button type="button" className="g-button g-danger" disabled={!live || cmd.pending} onClick={() => dialog.current?.showModal()}>
              Löschen
            </button>
          </div>
        </div>
        {wf.formats.length > 0 || canCandidates ? (
          <div className="g-form">
            {wf.formats.length > 0 ? (
              <div className="g-field">
                <label htmlFor={`${wf.key}-format`}>Format</label>
                <select
                  id={`${wf.key}-format`}
                  value={format}
                  onChange={(e) => {
                    const f = wf.formats.find((x) => x.name === e.target.value);
                    if (f) setRaw({ ...raw, width: String(f.width), height: String(f.height) });
                  }}
                >
                  {format === "" ? (
                    <option value="">
                      frei · {raw.width} × {raw.height}
                    </option>
                  ) : null}
                  {wf.formats.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name} · {f.width} × {f.height}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {canCandidates ? (
              <div className="g-field">
                <label htmlFor={`${wf.key}-candidates`}>Kandidaten</label>
                <input
                  id={`${wf.key}-candidates`}
                  type="number"
                  min={1}
                  max={ordersState?.candidatesMax ?? 1}
                  value={count === "" ? String(candidates) : count}
                  onChange={(e) => setCount(e.target.value)}
                />
              </div>
            ) : null}
            {canCandidates && finishers.length > 0 ? (
              <div className="g-field">
                <label htmlFor={`${wf.key}-finish`}>Fertigstellen mit</label>
                <select id={`${wf.key}-finish`} value={finish} onChange={(e) => setFinish(e.target.value)}>
                  <option value="">–</option>
                  {finishers.map((w) => (
                    <option key={w.key} value={w.key}>
                      {w.title}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>
        ) : null}
        {expertParams.length > 0 ? (
          <details className="g-expert" open={expert} onToggle={(e) => setExpert(e.currentTarget.open)}>
            <summary>Erweiterte Workflow-Einstellungen</summary>
            <div className="g-form">{expertParams.map(field)}</div>
          </details>
        ) : null}
        <button type="button" className="g-button g-primary g-block" disabled={!live || Boolean(blocked) || cmd.pending} onClick={() => void generate()}>
          {wf.training ? "Training starten" : "Generieren"}
        </button>
        {blocked ? <small>{blocked}</small> : null}
        {cmd.notice ? (
          <p className="g-note" role="alert">
            {cmd.notice}
          </p>
        ) : null}
        <Queue instance={wf.instance} onLoad={onLoad} canLoad={canLoad} />
        <Instances live={live} />
      </aside>

      {refPicking ? (
        <ReferencePicker
          onPick={(ref) => {
            setPickedRef((r) => ({ ...r, [refPicking.name]: ref }));
            setPicked((p) => ({ ...p, [refPicking.name]: undefined }));
          }}
          onClose={() => setRefPicking(null)}
        />
      ) : null}
      {picking ? (
        <MediaPicker title={`${paramLabel(picking, wf.kind)} aus Dateien`} onPick={(item) => pick(picking.name, item)} onClose={() => setPicking(null)} />
      ) : null}
      <dialog ref={dialog} className="g-dialog" aria-labelledby={`${wf.key}-delete`}>
        <h2 id={`${wf.key}-delete`}>Workflow löschen</h2>
        <p>
          „{wf.title}“ ({wf.key}) und seine Workflow-Dateien werden entfernt. Modelle, Ergebnisse und bisherige Aufträge
          bleiben erhalten.
        </p>
        <div className="g-actions">
          <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
            Abbrechen
          </button>
          <button
            type="button"
            className="g-button g-danger"
            onClick={() => {
              dialog.current?.close();
              void cmd.run({ case: "deleteWorkflow", value: { workflow: wf.key } }, { version });
            }}
          >
            Löschen
          </button>
        </div>
      </dialog>
    </>
  );
}

export function ComfyUI() {
  const instances = useStateTopic(Topic.COMFY_INSTANCES);
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value;
  const workflows = registry?.workflows ?? [];
  const version = registry?.version ?? 0n;
  const connection = useConnection();
  const [kind, setKind] = useState<Kind>("image");
  const [selected, setSelected] = useState<Record<Kind, string>>({ image: "", video: "", ai: "" });
  const [draft, setDraft] = useState<{ key: string; params: Record<string, string>; n: number } | null>(null);
  const [intent] = useState<RenderIntent | null>(takeRenderIntent);
  const canLoad = (key: string) => workflows.some((w) => w.key === key);

  function loadDraft(key: string, params: Record<string, string>) {
    const wf = workflows.find((w) => w.key === key);
    if (!wf) return;
    setKind(tabOf(wf));
    setSelected((s) => ({ ...s, [tabOf(wf)]: wf.key }));
    setDraft((d) => ({ key, params, n: (d?.n ?? 0) + 1 }));
  }

  const live = connection.status === "OPEN" && instances?.staleSince === null;
  const hasAi = instances?.value.instances.some((i) => i.name === "ai") ?? false;
  useEffect(() => {
    // Übergabe aus Dateien: Workflow wählen, sobald die Registry ihn meldet
    const target = intent && workflows.find((w) => w.key === intent.workflow);
    if (target) {
      setKind(tabOf(target));
      setSelected((s) => ({ ...s, [tabOf(target)]: target.key }));
    }
  }, [intent, workflows]);
  const list = workflows.filter((w) => tabOf(w) === kind);
  const current = list.find((w) => w.key === selected[kind]) ?? list[0];
  const comfyUrl = readyUrl(instances?.value.instances.find((i) => i.name === (current?.instance ?? "media")), live);
  const create = useCommand();
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [created, setCreated] = useState("");

  useEffect(() => {
    // nach dem Anlegen den neuen Workflow auswählen, sobald die Registry ihn meldet
    const fresh = workflows.find((w) => w.title === created);
    if (fresh) {
      setKind(tabOf(fresh));
      setSelected((s) => ({ ...s, [tabOf(fresh)]: fresh.key }));
      setCreated("");
    }
  }, [workflows, created]);

  function openCreate() {
    setTitle("");
    setSource(current?.key ?? "");
    dialog.current?.showModal();
  }

  async function submitCreate(e: FormEvent) {
    e.preventDefault();
    if (await create.run({ case: "createWorkflow", value: { source, title: title.trim() } }, { version })) {
      setCreated(title.trim());
      dialog.current?.close();
    }
  }

  return (
    <section className="g-panel">
      <h1>ComfyUI</h1>
      <div className="g-subtabs" role="tablist" aria-label="Workflow-Art">
        {KINDS.filter(([k]) => k !== "ai" || hasAi).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}>
            {label} <small>{workflows.filter((w) => tabOf(w) === k).length}</small>
          </button>
        ))}
      </div>

      <div className="g-studio">
        <div className="g-wflist" role="list" aria-label={`${KINDS.find(([k]) => k === kind)?.[1] ?? ""}-Workflows`}>
          <h2>Workflows</h2>
          <button type="button" className="g-button g-new" disabled={!live || list.length === 0} onClick={openCreate}>
            Neuer Workflow
          </button>
          {list.map((w) => (
            <button
              key={w.key}
              type="button"
              role="listitem"
              className="g-wfitem"
              aria-current={w === current ? "true" : undefined}
              onClick={() => setSelected({ ...selected, [kind]: w.key })}
            >
              <strong>{w.title}</strong>
              <small>
                {w.enabled ? "" : "deaktiviert · "}
                {w.modelsReady ? "bereit" : `fehlt ${w.missingGb.toFixed(1)} GB`} · {w.status}
              </small>
            </button>
          ))}
        </div>
        {current ? (
          <Workbench
            key={`${current.key}-${draft?.key === current.key ? draft.n : 0}-${intent?.workflow === current.key ? String(intent.media.mediaId) : ""}`}
            wf={current}
            workflows={workflows}
            version={version}
            live={live}
            comfyUrl={comfyUrl}
            draft={draft?.key === current.key ? draft.params : undefined}
            start={intent?.workflow === current.key ? intent.media : undefined}
            startParam={intent?.workflow === current.key ? intent.param : undefined}
            onLoad={loadDraft}
            canLoad={canLoad}
          />
        ) : (
          <>
            <div className="g-workmain">
              <p className="g-note">{connection.status === "OPEN" ? kind === "ai" ? "Keine KI-Workflows registriert (folgen in B5)." : "Keine registrierten Workflows." : "Keine Verbindung"}</p>
            </div>
            <aside className="g-control" aria-label="Steuerung">
              <h2>Steuerung</h2>
              <Queue instance={kind === "ai" ? "ai" : "media"} onLoad={loadDraft} canLoad={canLoad} />
              <Instances live={live} />
            </aside>
          </>
        )}
      </div>

      <dialog ref={dialog} className="g-dialog" aria-labelledby="wf-create">
        <form className="g-form" onSubmit={submitCreate}>
          <h2 id="wf-create" className="g-wide">
            Neuer Workflow
          </h2>
          <div className="g-field g-wide">
            <label htmlFor="wf-create-title">Titel</label>
            <input id="wf-create-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="g-field g-wide">
            <label htmlFor="wf-create-source">Vorlage</label>
            <select id="wf-create-source" value={source} onChange={(e) => setSource(e.target.value)}>
              {list.map((w) => (
                <option key={w.key} value={w.key}>
                  {w.title}
                </option>
              ))}
            </select>
          </div>
          {create.notice ? (
            <p className="g-note g-wide" role="alert">
              {create.notice}
            </p>
          ) : null}
          <div className="g-actions g-wide">
            <button type="button" className="g-button" onClick={() => dialog.current?.close()}>
              Abbrechen
            </button>
            <button type="submit" className="g-button g-primary" disabled={!title.trim() || !source || create.pending}>
              Anlegen
            </button>
          </div>
        </form>
      </dialog>
    </section>
  );
}
