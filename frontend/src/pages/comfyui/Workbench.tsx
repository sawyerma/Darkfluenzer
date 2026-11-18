import { VIDEO_ORDER, VideoSettings } from "./VideoSettings";
import { Candidates } from "./Candidates";
import { CharacterControl, TrainingFolder, useCharacter } from "./Character";
import { Instances } from "./Instances";
import { LABEL, WORKFLOW_GATE, duration, gate } from "./common";
import { LoadDraft, Queue } from "./Queue";
import type { MediaItem } from "../../core/generated/darkfluenzer/v1/media_pb";
import { MediaPicker } from "../Files";
import type { ReferenceItem } from "../../core/generated/darkfluenzer/v1/reference_pb";
import { ReferencePicker, WorkflowResults } from "./Results";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import type { WorkflowInfo, WorkflowParam } from "../../core/generated/darkfluenzer/v1/comfy_pb";
import { mediaUrl } from "../../core/media";
import { useCommand } from "../../core/commands";
import { useEffect, useRef, useState } from "react";
import { useStateTopic } from "../../core/state";

/** Felder vor dem Startbild und der Videosteuerung (SP1 Schritt 10). */
const FIRST_FIELDS = ["prompt", "negative_prompt"];

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

/** Arbeitsfläche (Mitte) und Steuerung (rechts) des gewählten Workflows (F7.5). */
export function Workbench({
  wf,
  workflows,
  version,
  live,
  comfyUrl,
  draft,
  start,
  startParam,
  customerOrder,
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
  customerOrder?: string; // bezahlter Kundenauftrag aus der Auftragskarte (V0 §8.4 Punkt 5)
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
  // weitere Schlüsselbilder zwischen Start- und Endbild (Zeitachse B4): Zeit (s), Bild (Upload
  // oder Medium aus Dateien, Backend prüft den SHA-256), Stärke
  const [keyframes, setKeyframes] = useState<{ at: string; file?: File; media?: MediaItem; strength: string }[]>([]);
  const [kfPicking, setKfPicking] = useState<number | null>(null);
  const [finish, setFinish] = useState("");
  // Kundenauftrag: nur bezahlte (Status paid) und nur Workflows der Inhaltsstufe standard (Regel 13)
  const awaiting = ordersState?.awaitingProduction ?? [];
  const [chosenOrder, setChosenOrder] = useState(customerOrder ?? "");
  const forOrder = wf.content === "standard" && awaiting.some((o) => o.orderNo === chosenOrder) ? chosenOrder : "";
  // Video: ein Kandidat, solange nicht bewusst mehr gewählt (ein LTX-Lauf ~19 min, BUG-044)
  const candidates = count === "" ? (wf.kind === "video" ? 1 : (ordersState?.candidatesDefault ?? 1)) : Number(count);
  const titles = Object.fromEntries(workflows.map((w) => [w.key, w.title]));
  const mine = (useStateTopic(Topic.JOBS_ACTIVE)?.value.jobs ?? []).filter((j) => j.workflow === wf.key);
  const running = mine.find((j) => j.running);
  const waiting = mine.filter((j) => !j.running).length;
  const dialog = useRef<HTMLDialogElement>(null);
  const [raw, setRaw] = useState<Record<string, string>>(() =>
    Object.fromEntries(wf.params.filter((p) => !p.upload).map((p) => [p.name, draft?.[p.name] ?? defaultText(p)])),
  );
  const videoS = Number(raw.duration_s ?? 0); // Länge der Zeitleiste (B4)
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
  // Charakter-LoRA (SP3 Schritt 5/6): ladbare LoRAs des Workflows, aktive Version der Figur
  // vorbelegt (null = Vorbelegung), dazu „ohne“; Stärke startet mit dem Wert der LoRA
  const loraInfo = new Map(chars.list.flatMap((c) => c.loras.map((l) => [l.key, { strength: l.strength, active: l.active, owner: c.name }] as const)));
  const activeLora = character?.loras.find((l) => l.active && wf.loras.includes(l.key))?.key ?? "";
  const [loraChoice, setLoraChoice] = useState<string | null>(null);
  const lora = wf.loraSlot ? (loraChoice ?? activeLora) : "";
  const loraStrength = loraInfo.get(lora)?.strength;
  useEffect(() => {
    if (loraStrength !== undefined && wf.params.some((p) => p.name === "character_strength")) {
      setRaw((r) => ({ ...r, character_strength: String(loraStrength) }));
    }
  }, [lora, loraStrength, wf.params]);
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
          : forOrder && wf.loraSlot && !lora
            ? "Kundenauftrag nur mit Charakter-LoRA"
            : "";

  async function generate() {
    setChecked(true);
    if (Object.values(errors).some(Boolean)) {
      if (expertParams.some((p) => errors[p.name])) setExpert(true); // Fehler sichtbar machen
      return;
    }
    const values = wf.params
      .filter((p) => !p.upload && (lora || p.name !== "character_strength"))
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
    const frames = await Promise.all(
      keyframes
        .filter((k) => k.file || k.media)
        .map(async (k) => ({
          atS: Number(k.at),
          strength: Number(k.strength),
          file: k.media
            ? { param: "", filename: k.media.path.split("/").pop() ?? "", mediaId: k.media.mediaId }
            : { param: "", filename: k.file!.name, data: new Uint8Array(await k.file!.arrayBuffer()) },
        })),
    );
    const asOrder = forOrder !== "" || lora !== "" || (canCandidates && (candidates > 1 || finish !== ""));
    const jobs = canCandidates ? candidates : 1;
    const done = asOrder
      ? await cmd.run(
          {
            case: "createOrder",
            value: { workflow: wf.key, values, files: inputs, parentMediaId, candidates: jobs, finishWorkflow: finish, customerOrderNo: forOrder, lora, keyframes: frames },
          },
          { version, done: forOrder ? `Kundenauftrag ${forOrder}: ${jobs} Kandidaten eingereiht.` : `${jobs} Kandidaten eingereiht.` },
        )
      : await cmd.run(
          {
            case: "render",
            value: { workflow: wf.key, values, files: inputs, parentMediaId, characterId: wf.usesCharacter && character ? BigInt(character.id) : 0n, keyframes: frames },
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

  const expertParams = wf.params.filter(
    (p) => !inMain(p) && !(wf.kind === "video" && VIDEO_ORDER.includes(p.name)) && (lora || p.name !== "character_strength"),
  );
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
        {wf.training ? <TrainingFolder character={character} version={version} /> : null}
        <div className="g-form">
          {wf.kind === "video" ? (
            <>
              {wf.params.filter((p) => inMain(p) && !p.upload && FIRST_FIELDS.includes(p.name)).map(field)}
              {wf.params.filter((p) => p.upload && !p.reference).map(field)}
              <VideoSettings params={wf.params} field={field} />
              {wf.params.filter((p) => inMain(p) && !p.upload && !FIRST_FIELDS.includes(p.name) && !VIDEO_ORDER.includes(p.name)).map(field)}
            </>
          ) : (
            [...wf.params.filter((p) => inMain(p) && !p.upload), ...wf.params.filter((p) => p.upload && !p.reference)].map(field)
          )}
        </div>
        <Candidates orders={myOrders} titles={titles} />
        <WorkflowResults wf={wf} running={running} waiting={waiting} onLoad={onLoad} canLoad={canLoad} />
      </div>

      <aside className="g-control" aria-label="Steuerung">
        <h2>Steuerung</h2>
        <div className="g-control-part">
          <CharacterControl training={wf.usesCharacter} {...chars} />
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
              <span className="g-badge" data-tone={gate(WORKFLOW_GATE, wf.status)[1]} title={gate(WORKFLOW_GATE, wf.status)[3]}>
                {gate(WORKFLOW_GATE, wf.status)[0]}
              </span>
            </span>
          </div>
          <small>
            {wf.modelsReady ? "Modelle bereit" : `fehlt ${wf.missingGb.toFixed(1)} GB`}
            {wf.usage === "production" ? "" : " · nur Evaluation"}
            {wf.editorChanged ? " · im Editor geändert" : ""}
            {wf.selectionTotal ? ` · Prüfung bestanden ${wf.selectionPassed}/${wf.selectionTotal}` : ""}
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
        {!wf.training && (awaiting.length > 0 || customerOrder) ? (
          <div className="g-field">
            <label htmlFor={`${wf.key}-customer`}>Für Kundenauftrag</label>
            {wf.content === "standard" ? (
              <select id={`${wf.key}-customer`} value={forOrder} onChange={(e) => setChosenOrder(e.target.value)}>
                <option value="">– eigener Auftrag</option>
                {awaiting.map((o) => (
                  <option key={o.orderNo} value={o.orderNo}>
                    {o.orderNo} · {o.customerNo} · {o.offer?.product ?? ""}
                    {o.offer?.hd ? " + HD" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <small>
                {chosenOrder ? `Für ${chosenOrder} einen` : "Kundenaufträge nur mit einem"} Workflow der Inhaltsstufe standard wählen
                (dieser: {wf.content || "explizit"}).
              </small>
            )}
            {customerOrder && !awaiting.some((o) => o.orderNo === customerOrder) ? (
              <small>{customerOrder} wartet nicht mehr auf die Produktion.</small>
            ) : null}
          </div>
        ) : null}
        {wf.keyframes ? (
          <div className="g-field">
            <label>Weitere Schlüsselbilder</label>
            {videoS > 0 ? (
              <svg
                className="g-timeline"
                viewBox="0 0 1000 20"
                preserveAspectRatio="none"
                role="button"
                tabIndex={0}
                aria-label="Zeitleiste: Klick setzt ein Schlüsselbild"
                onClick={(e) => {
                  const box = e.currentTarget.getBoundingClientRect();
                  const at = Math.round(((e.clientX - box.left) / box.width) * videoS * 10) / 10;
                  if (at > 0 && at < videoS) setKeyframes([...keyframes, { at: String(at), strength: "0.8" }].sort((a, b) => Number(a.at) - Number(b.at)));
                }}
              >
                <title>Klick setzt ein Schlüsselbild</title>
                <rect className="g-timeline-mark" data-edge="" x={6} y={3} width={8} height={14}>
                  <title>Start 0 s</title>
                </rect>
                {keyframes.map((k, i) => {
                  const at = Number(k.at);
                  const inside = at > 0 && at < videoS;
                  const x = Math.min(990, Math.max(6, (at / videoS) * 1000 - 4));
                  return (
                    <rect key={i} className="g-timeline-mark" data-tone={inside && (k.file || k.media) ? undefined : "bad"} x={x} y={3} width={8} height={14}>
                      <title>{`${k.at} s${inside ? "" : " · außerhalb"}${k.file || k.media ? "" : " · Bild fehlt"}`}</title>
                    </rect>
                  );
                })}
                <rect className="g-timeline-mark" data-edge="" x={986} y={3} width={8} height={14}>
                  <title>{`Ende ${videoS} s`}</title>
                </rect>
              </svg>
            ) : null}
            {keyframes.map((k, i) => (
              <div key={i} className="g-keyframe">
                <span className="g-keyframe-values">
                  <small>Zeit (s)</small>
                  <small>Stärke</small>
                  <input
                    className="g-input"
                    type="number"
                    min={0}
                    step={0.1}
                    aria-label="Zeitpunkt (s)"
                    value={k.at}
                    onChange={(e) => setKeyframes(keyframes.map((x, j) => (j === i ? { ...x, at: e.target.value } : x)))}
                  />
                  <input
                    className="g-input"
                    type="number"
                    min={0.1}
                    max={1}
                    step={0.05}
                    aria-label="Stärke"
                    value={k.strength}
                    onChange={(e) => setKeyframes(keyframes.map((x, j) => (j === i ? { ...x, strength: e.target.value } : x)))}
                  />
                </span>
                {k.media ? (
                  <small className="g-ellipsis" title={`local/${k.media.path}`}>
                    {k.media.path.split("/").pop()}
                  </small>
                ) : (
                  <input
                    className="g-input"
                    type="file"
                    accept="image/*"
                    aria-label="Bild"
                    onChange={(e) => setKeyframes(keyframes.map((x, j) => (j === i ? { ...x, file: e.target.files?.[0], media: undefined } : x)))}
                  />
                )}
                <span className="g-actions">
                  <button type="button" className="g-button" onClick={() => setKfPicking(i)}>
                    Aus Dateien
                  </button>
                  <button type="button" className="g-button" onClick={() => setKeyframes(keyframes.filter((_, j) => j !== i))}>
                    Entfernen
                  </button>
                </span>
              </div>
            ))}
            <button type="button" className="g-button" onClick={() => setKeyframes([...keyframes, { at: "1", strength: "0.8" }])}>
              Schlüsselbild hinzufügen
            </button>
          </div>
        ) : null}
        {wf.loraSlot ? (
          <div className="g-field">
            <label htmlFor={`${wf.key}-lora`}>Charakter-LoRA</label>
            <select id={`${wf.key}-lora`} className="g-input" value={lora} onChange={(e) => setLoraChoice(e.target.value)}>
              <option value="">ohne Charakter-LoRA</option>
              {wf.loras.map((k) => (
                <option key={k} value={k}>
                  {[loraInfo.get(k)?.owner, k].filter(Boolean).join(" · ")}
                  {loraInfo.get(k)?.active ? " (aktiv)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}
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
                  {finishers.filter((w) => !forOrder || w.content === "standard").map((w) => (
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
        {wf.training ? (
          <p className="g-note">
            Gesamtschritte {raw.steps || "?"} ·{" "}
            {wf.stepS > 0 && Number(raw.steps) > 0 ? `geschätzt ${duration(Number(raw.steps) * wf.stepS)}` : "Dauer: noch keine Messung"}
          </p>
        ) : null}
        <button type="button" className="g-button g-primary g-block" disabled={!live || Boolean(blocked) || cmd.pending} onClick={() => void generate()}>
          {wf.training ? "Training starten" : "Generieren"}
        </button>
        {blocked ? <small>{blocked}</small> : null}
        {checked && wf.params.some((p) => errors[p.name]) ? (
          <small className="g-error" role="alert">
            Prüfen: {wf.params.filter((p) => errors[p.name]).map((p) => `${paramLabel(p, wf.kind)} – ${errors[p.name]}`).join(" · ")}
          </small>
        ) : null}
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
      {kfPicking !== null ? (
        <MediaPicker
          title="Schlüsselbild aus Dateien"
          onPick={(item) => setKeyframes(keyframes.map((x, j) => (j === kfPicking ? { ...x, media: item, file: undefined } : x)))}
          onClose={() => setKfPicking(null)}
        />
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
