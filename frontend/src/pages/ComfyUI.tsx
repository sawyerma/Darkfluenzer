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
import { fetchMediaFile, mediaUrl } from "../core/media";
import { useConnection } from "../core/realtime";
import { type MediaItem } from "../core/generated/darkfluenzer/v1/media_pb";
import { useEventTopic, useStateTopic, type StateValue } from "../core/state";
import { MediaPicker } from "./Files";

type Tone = "ok" | "warn" | "bad" | "neutral";
type Kind = "image" | "video";

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
];
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

/** Ein Befehl mit sichtbarem Ergebnis: läuft, Ablehnungsgrund oder Fehler. */
function paramLabel(p: WorkflowParam, kind: string): string {
  if (p.name === "prompt") return kind === "video" ? "Szene und Bewegung" : "Motiv, Komposition, Perspektive, Licht";
  if (p.name === "image") return kind === "video" ? "Startbild" : "Quellbild";
  return LABEL[p.name] ?? p.name;
}

function defaultText(p: WorkflowParam): string {
  return p.default.case === undefined ? "" : String(p.default.value);
}

function validate(p: WorkflowParam, raw: string, file: File | undefined): string {
  if (p.upload) return p.required && !file ? "Datei wählen" : "";
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

function Instance({ comfy, live }: { comfy: StateValue<ComfyStatus> | undefined; live: boolean }) {
  const cmd = useCommand();
  const s = comfy?.value;
  const ready = live && (s?.state === ComfyState.READY || s?.state === ComfyState.BUSY);
  const showStart = s?.state === ComfyState.STOPPED || s?.state === ComfyState.FAILED;
  // Stoppen nur ohne laufenden Auftrag und nur die eigene Instanz
  const showStop = s?.managed === true && (s.state === ComfyState.READY || s.state === ComfyState.UNREACHABLE);
  return (
    <div className="g-section">
      <div className="g-line">
        <span>Instanz</span>
        <span className="g-value">
          {s && s.queueRunning + s.queuePending > 0 ? (
            <small>
              {s.queueRunning} läuft · {s.queuePending} wartet
            </small>
          ) : null}
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
          <button type="button" className="g-button g-primary" disabled={!live || cmd.pending} onClick={() => cmd.run({ case: "comfyStart", value: {} })}>
            Starten
          </button>
        ) : null}
        {showStop ? (
          <button type="button" className="g-button" disabled={!live || cmd.pending} onClick={() => cmd.run({ case: "comfyStop", value: {} })}>
            Stoppen
          </button>
        ) : null}
        {ready && s ? (
          <a className="g-button" href={s.url} target="_blank" rel="noreferrer">
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

function WorkflowDetail({
  wf,
  live,
  comfyUrl,
  draft,
}: {
  wf: WorkflowInfo;
  live: boolean;
  comfyUrl: string;
  draft?: Record<string, string>;
}) {
  const cmd = useCommand();
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
  // Eingabebild aus der Galerie: dieselbe Datei wie beim Hochladen, Herkunft sichtbar
  const [picked, setPicked] = useState<Record<string, MediaItem | undefined>>({});
  const [picking, setPicking] = useState<WorkflowParam | null>(null);
  const [pickError, setPickError] = useState("");
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const [checked, setChecked] = useState(false);
  const errors = Object.fromEntries(wf.params.map((p) => [p.name, validate(p, raw[p.name] ?? "", files[p.name])]));
  const blocked = !wf.enabled
    ? "Deaktiviert"
    : wf.status === "GESPERRT"
      ? "Gesperrt"
      : !wf.modelsReady
        ? `Modelle fehlen (${wf.missingGb.toFixed(1)} GB)`
        : "";

  async function generate(e: FormEvent) {
    e.preventDefault();
    setChecked(true);
    if (Object.values(errors).some(Boolean)) return;
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
        .filter((p) => p.upload && files[p.name])
        .map(async (p) => {
          const file = files[p.name]!;
          return { param: p.name, filename: file.name, data: new Uint8Array(await file.arrayBuffer()) };
        }),
    );
    if (await cmd.run({ case: "render", value: { workflow: wf.key, values, files: inputs } }, "Eingereiht.")) {
      setChecked(false);
    }
  }

  async function pick(param: string, item: MediaItem) {
    setPickError("");
    try {
      const file = await fetchMediaFile(item);
      const input = fileInputs.current[param];
      if (input) {
        // Dateifeld zeigt die gewählte Datei wie nach eigener Auswahl
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
      }
      setFiles((f) => ({ ...f, [param]: file }));
      setPicked((p) => ({ ...p, [param]: item }));
    } catch (e) {
      setPickError(e instanceof Error ? e.message : String(e));
    }
  }

  async function openInEditor() {
    // Tab sofort im Klick öffnen (sonst blockiert der Browser), Ziel erst nach Freigabe setzen.
    const tab = window.open("", "darkfluenzer-comfyui");
    if (await cmd.run({ case: "openWorkflow", value: { workflow: wf.key } })) {
      if (tab) tab.location.href = `${comfyUrl}/?workflows=${encodeURIComponent(wf.key)}`;
    } else {
      tab?.close();
    }
  }

  return (
    <div className="g-wfdetail" ref={top}>
      <div className="g-line">
        <div>
          <h2>{wf.title}</h2>
          <small>{wf.engineTitle}</small>
        </div>
        <label className="g-switch">
          <input
            type="checkbox"
            role="switch"
            checked={wf.enabled}
            disabled={!live || cmd.pending}
            onChange={(e) => cmd.run({ case: "setWorkflowEnabled", value: { workflow: wf.key, enabled: e.target.checked } })}
          />
          Aktiviert
        </label>
      </div>
      <div className="g-line">
        <span className="g-value">
          {wf.modelsReady ? "Modelle bereit" : `fehlt ${wf.missingGb.toFixed(1)} GB`}
          {wf.usage === "production" ? "" : " · nur Evaluation"}
          {wf.editorChanged ? " · im Editor geändert" : ""}
        </span>
        <span className="g-badge" data-tone={WORKFLOW_TONE[wf.status] ?? "neutral"}>
          {wf.status}
        </span>
      </div>
      <div className="g-actions">
        <button type="button" className="g-button" disabled={!live || !comfyUrl || cmd.pending} onClick={openInEditor}>
          Öffnen
        </button>
        {wf.editorChanged ? (
          <button
            type="button"
            className="g-button"
            disabled={!live || !comfyUrl || cmd.pending}
            onClick={() => cmd.run({ case: "adoptWorkflow", value: { workflow: wf.key } }, "Übernommen.")}
          >
            Änderung übernehmen
          </button>
        ) : null}
        <button type="button" className="g-button g-danger" disabled={!live || cmd.pending} onClick={() => dialog.current?.showModal()}>
          Löschen
        </button>
      </div>

      {draft ? (
        <p className="g-note">
          Aus einem Auftrag geladen{wf.params.some((p) => p.upload) ? " – Bilddateien neu wählen." : "."}
        </p>
      ) : null}
      <form className="g-form" noValidate onSubmit={generate}>
        {wf.params.map((p) => {
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
        })}
        {pickError ? (
          <p className="g-note g-wide" role="alert">
            {pickError}
          </p>
        ) : null}
        <div className="g-actions g-wide">
          <button type="submit" className="g-button g-primary" disabled={!live || Boolean(blocked) || cmd.pending}>
            Generieren
          </button>
          {blocked ? <small>{blocked}</small> : null}
          {running ? <Progress job={running} /> : null}
          {waiting ? <small>{waiting} wartend</small> : null}
        </div>
      </form>
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}

      {picking ? (
        <MediaPicker
          title={`${paramLabel(picking, wf.kind)} aus Dateien`}
          onPick={(item) => void pick(picking.name, item)}
          onClose={() => setPicking(null)}
        />
      ) : null}
      <dialog ref={dialog} className="g-dialog" aria-labelledby={`${wf.key}-delete`}>
        <h2 id={`${wf.key}-delete`}>Workflow löschen</h2>
        <p>
          „{wf.title}“ ({wf.key}) und seine Workflow-Dateien werden entfernt. Modelle, Ergebnisse und bisherige
          Aufträge bleiben erhalten.
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
              void cmd.run({ case: "deleteWorkflow", value: { workflow: wf.key } });
            }}
          >
            Löschen
          </button>
        </div>
      </dialog>
    </div>
  );
}

type LoadDraft = (workflow: string, params: Record<string, string>) => void;
const FIRST_PARAMS = ["prompt", "negative_prompt"];
const FILE_PARAMS = new Set(["image", "mask"]);

/** Parameter eines Auftrags zum Nachsehen; Eingabedateien mit ihrem Namen. */
function JobParams({ params }: { params: Record<string, string> }) {
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
          <dt>{n === "prompt" ? "Prompt" : n === "image" ? "Bild" : (LABEL[n] ?? n)}</dt>
          <dd>{FILE_PARAMS.has(n) ? params[n]!.split("/").pop() : params[n]}</dd>
        </div>
      ))}
    </dl>
  );
}

function Queue({ onLoad, canLoad }: { onLoad: LoadDraft; canLoad: (key: string) => boolean }) {
  const active = useStateTopic(Topic.JOBS_ACTIVE)?.value;
  const jobs = active?.jobs ?? [];
  const cmd = useCommand();
  const [open, setOpen] = useState<bigint | null>(null);
  return (
    <div className="g-section">
      <div className="g-line g-head">
        <h2>Warteschlange</h2>
        <span className="g-value">
          {active?.paused ? (
            <span className="g-badge" data-tone="warn">
              ANGEHALTEN
            </span>
          ) : null}
          <button
            type="button"
            className="g-button"
            disabled={!active || cmd.pending}
            onClick={() => cmd.run({ case: "pauseQueue", value: { paused: !active?.paused } })}
          >
            {active?.paused ? "Fortsetzen" : "Anhalten"}
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
                  <JobParams params={job.params} />
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

function Results({ onLoad, canLoad }: { onLoad: LoadDraft; canLoad: (key: string) => boolean }) {
  const results = useEventTopic(Topic.JOB_COMPLETED);
  const removed = useEventTopic(Topic.MEDIA_REMOVED);
  const gone = useMemo(() => new Set(removed?.items.map((e) => e.value.path)), [removed]);
  const connection = useConnection();
  const [open, setOpen] = useState<bigint | null>(null);
  const recent = results ? [...results.items].reverse().slice(0, 8) : [];
  return (
    <div className="g-section">
      <h2>Ergebnisse</h2>
      {results?.gap ? <p className="g-note">Ältere Ergebnisse nicht nachgeladen.</p> : null}
      {recent.length > 0 ? (
        recent.map(({ cursor, committedMs, value: job }) => {
          const isOpen = open === cursor;
          const [label, tone] = RESULT_BADGE[job.result];
          return (
            <div className="g-qitem" key={String(cursor)}>
              <div className="g-line">
                <span className="g-value">
                  {job.outputs
                    .filter((o) => IMAGE.test(o.path) && !gone.has(o.path))
                    .slice(0, 1)
                    .map((o) => (
                      <a key={o.path} href={mediaUrl(o.path)} target="_blank" rel="noreferrer">
                        <img className="g-thumb" src={mediaUrl(o.path)} alt={job.workflow} loading="lazy" />
                      </a>
                    ))}
                  <button
                    type="button"
                    className="g-row g-ellipsis"
                    aria-expanded={isOpen}
                    onClick={() => setOpen(isOpen ? null : cursor)}
                  >
                    {job.workflow}
                  </button>
                </span>
                <span className="g-value g-nowrap">
                  {clock(committedMs)}
                  <span className="g-badge" data-tone={tone}>
                    {label}
                  </span>
                </span>
              </div>
              {job.result === JobResult.FAILED && job.error ? <p className="g-note g-error">{job.error}</p> : null}
              {isOpen ? (
                <div className="g-details">
                  <JobParams params={job.params} />
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
        })
      ) : (
        <p className="g-note">
          {results?.live ? "Noch keine Renderung über Darkfluenzer." : connection.status === "OPEN" ? "Lädt …" : "Keine Verbindung"}
        </p>
      )}
    </div>
  );
}

export function ComfyUI() {
  const comfy = useStateTopic(Topic.COMFY_STATUS);
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const connection = useConnection();
  const [kind, setKind] = useState<Kind>("image");
  const [selected, setSelected] = useState<Record<Kind, string>>({ image: "", video: "" });
  const [draft, setDraft] = useState<{ key: string; params: Record<string, string>; n: number } | null>(null);
  const canLoad = (key: string) => workflows.some((w) => w.key === key);

  function loadDraft(key: string, params: Record<string, string>) {
    const wf = workflows.find((w) => w.key === key);
    if (!wf) return;
    setKind(wf.kind as Kind);
    setSelected((s) => ({ ...s, [wf.kind]: wf.key }));
    setDraft((d) => ({ key, params, n: (d?.n ?? 0) + 1 }));
  }

  const live = connection.status === "OPEN" && comfy?.staleSince === null;
  const s = comfy?.value;
  const comfyUrl = live && (s?.state === ComfyState.READY || s?.state === ComfyState.BUSY) ? s.url : "";
  const list = workflows.filter((w) => w.kind === kind);
  const current = list.find((w) => w.key === selected[kind]) ?? list[0];
  const create = useCommand();
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [created, setCreated] = useState("");

  useEffect(() => {
    // nach dem Anlegen den neuen Workflow auswählen, sobald die Registry ihn meldet
    const fresh = workflows.find((w) => w.title === created);
    if (fresh) {
      setKind(fresh.kind as Kind);
      setSelected((s) => ({ ...s, [fresh.kind]: fresh.key }));
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
    if (await create.run({ case: "createWorkflow", value: { source, title: title.trim() } })) {
      setCreated(title.trim());
      dialog.current?.close();
    }
  }

  return (
    <section className="g-panel">
      <h1>ComfyUI</h1>
      <Instance comfy={comfy} live={live} />

      <div className="g-subtabs" role="tablist" aria-label="Workflow-Art">
        {KINDS.map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}>
            {label} <small>{workflows.filter((w) => w.kind === k).length}</small>
          </button>
        ))}
      </div>

      <div className="g-studio">
        <div className="g-wflist" role="list" aria-label={kind === "image" ? "Foto-Workflows" : "Video-Workflows"}>
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
          <WorkflowDetail
            key={`${current.key}-${draft?.key === current.key ? draft.n : 0}`}
            wf={current}
            live={live}
            comfyUrl={comfyUrl}
            draft={draft?.key === current.key ? draft.params : undefined}
          />
        ) : (
          <p className="g-note">{connection.status === "OPEN" ? "Keine registrierten Workflows." : "Keine Verbindung"}</p>
        )}
        <div className="g-side">
          <Queue onLoad={loadDraft} canLoad={canLoad} />
          <Results onLoad={loadDraft} canLoad={canLoad} />
        </div>
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
