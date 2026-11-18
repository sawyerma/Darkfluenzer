import type { Character } from "../../core/generated/darkfluenzer/v1/character_pb";
import { type FormEvent, useState } from "react";
import { LORA_GATE, PHOTO_STATUS, gate } from "./common";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useCommand } from "../../core/commands";
import { useStateTopic } from "../../core/state";

// Gewähltes Charakterprofil (F7.5 „Charakter“); bleibt beim Wechsel des Workflows erhalten.
let chosenCharacter = "";

export function useCharacter() {
  const list = useStateTopic(Topic.CHARACTERS)?.value.characters ?? [];
  const [id, setId] = useState(chosenCharacter);
  const current = list.find((c) => c.id === id) ?? list[0];
  function choose(next: string) {
    chosenCharacter = next;
    setId(next);
  }
  return { list, current, choose };
}

/** Größte Summe je Befehl beim Ablegen (der Befehl selbst ist durch server.max_upload_mb begrenzt). */
const PHOTO_BATCH_BYTES = 40 * 1024 * 1024;

/** Charakter (Steuerung, F7.5, SP3 Schritt 1): Profil wählen, anlegen (Name, Kürzel, Trigger,
 *  Klasse), bearbeiten; Ordner local/characters/<kürzel>/ zum Kopieren und im Finder, Fotos per
 *  Ziehen/Ablegen (Befehle 25, 65, 67). */
export function CharacterControl({ training, list, current, choose }: { training: boolean } & ReturnType<typeof useCharacter>) {
  const cmd = useCommand();
  const [editing, setEditing] = useState<"" | "new" | "edit">("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [trigger, setTrigger] = useState("");
  const [classWord, setClassWord] = useState("");
  const [probes, setProbes] = useState("");
  const [over, setOver] = useState<"" | "photos" | "reference">("");

  function startEdit(mode: "new" | "edit") {
    setName(mode === "edit" && current ? current.name : "");
    setSlug("");
    setTrigger(mode === "edit" && current ? current.trigger : "");
    setClassWord(mode === "edit" && current ? current.classWord : "");
    setProbes(mode === "edit" && current ? current.probePrompts.join("\n") : "");
    setEditing(mode);
  }

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
          trigger: trigger.trim(),
          classWord: classWord.trim(),
          slug: create ? slug.trim() : "",
          probePrompts: probes.split("\n").map((l) => l.trim()).filter(Boolean),
        },
      },
      { done: create ? "Charakter angelegt." : "Übernommen." },
    );
    if (done) setEditing("");
  }

  async function addPhotos(part: "photos" | "reference", files: File[]) {
    if (!current || files.length === 0) return;
    let batch: File[] = [];
    let size = 0;
    const send = async () => {
      if (batch.length === 0) return;
      const items = await Promise.all(batch.map(async (f) => ({ param: "", filename: f.name, data: new Uint8Array(await f.arrayBuffer()) })));
      await cmd.run({ case: "characterPhotosAdd", value: { characterId: BigInt(current.id), part, files: items } }, { done: `${files.length} Datei(en) übernommen.` });
      batch = [];
      size = 0;
    };
    for (const f of files) {
      if (size + f.size > PHOTO_BATCH_BYTES) await send();
      batch.push(f);
      size += f.size;
    }
    await send();
  }

  function dropZone(part: "photos" | "reference", label: string) {
    return (
      <div
        className="g-drop"
        data-over={over === part ? "" : undefined}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(part);
        }}
        onDragLeave={() => setOver("")}
        onDrop={(e) => {
          e.preventDefault();
          setOver("");
          void addPhotos(part, Array.from(e.dataTransfer.files));
        }}
      >
        <small>{label}</small>
      </div>
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
                startEdit("new");
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
            <button type="button" className="g-button" onClick={() => startEdit("edit")}>
              Bearbeiten
            </button>
          ) : null}
        </span>
      </div>
      {editing ? (
        <form className="g-form" onSubmit={save}>
          <input className="g-input" aria-label="Name des Charakters" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          {editing === "new" ? (
            <input className="g-input g-mono" aria-label="Kürzel" placeholder="Kürzel (leer: aus dem Namen)" value={slug} onChange={(e) => setSlug(e.target.value)} />
          ) : null}
          <input className="g-input g-mono" aria-label="Trigger" placeholder="Trigger (z. B. clara01)" value={trigger} onChange={(e) => setTrigger(e.target.value)} />
          <input className="g-input" aria-label="Klasse" placeholder="Klasse (z. B. woman)" value={classWord} onChange={(e) => setClassWord(e.target.value)} />
          <textarea className="g-input" aria-label="Probe-Prompts" placeholder="Probe-Prompts (einer je Zeile)" rows={3} value={probes} onChange={(e) => setProbes(e.target.value)} />
          <span className="g-actions">
            <button type="submit" className="g-button g-primary" disabled={cmd.pending || !name.trim() || !trigger.trim() || !classWord.trim()}>
              {editing === "new" ? "Anlegen" : "Übernehmen"}
            </button>
            <button type="button" className="g-button" onClick={() => setEditing("")}>
              Abbrechen
            </button>
          </span>
        </form>
      ) : null}
      {training && current ? (
        <div className="g-field">
          <label>Trainingsfotos</label>
          <code className="g-mono">{current.photosDir}</code>
          <span className="g-between">
            <button type="button" className="g-button" onClick={() => void navigator.clipboard.writeText(current.folder)}>
              Pfad kopieren
            </button>
            <button
              type="button"
              className="g-button"
              disabled={cmd.pending}
              onClick={() => void cmd.run({ case: "revealFolder", value: { characterId: BigInt(current.id), part: "photos" } })}
            >
              Im Finder öffnen
            </button>
          </span>
          {dropZone("photos", "Trainingsfotos hierher ziehen")}
          {dropZone("reference", "Referenzfotos (Gesicht, 5–10) hierher ziehen")}
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
export function TrainingFolder({ character, version }: { character: Character | undefined; version: bigint }) {
  const cmd = useCommand();
  if (!character) return <p className="g-note">Keine Daten zum Trainingsordner.</p>;
  // Fortsetzen: derselbe Lauf setzt beim letzten Checkpoint fort; Beenden: Gesamtschritte = Schritt
  // des Checkpoints, die LoRA entsteht aus dessen Gewichten (SP3 Schritt 3)
  const continueRun = (cp: (typeof character.checkpoints)[number], finish: boolean) =>
    void cmd.run(
      {
        case: "render",
        value: {
          workflow: cp.workflow,
          repeatJobId: cp.jobId,
          characterId: BigInt(character.id),
          values: finish ? [{ name: "steps", value: { case: "integer", value: BigInt(cp.step) } }] : [],
          files: [],
          parentMediaId: 0n,
        },
      },
      { version, acceptedOnly: true, done: finish ? "Beenden eingereiht." : "Fortsetzen eingereiht." },
    );
  // Aktive LoRA je Architektur setzen oder aufheben (Befehl 64, SP3 Schritt 6)
  const activate = (lora: string, arch: string) =>
    void cmd.run({ case: "loraActivate", value: { characterId: BigInt(character.id), lora, arch } }, { done: lora ? "Aktiv gesetzt." : "Aufgehoben." });
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
      {character.checkpoints.map((cp) => (
        <div className="g-line" key={cp.run}>
          <span className="g-ellipsis" title={cp.run}>
            Checkpoint {cp.step} von {cp.total}
            {cp.loss ? ` · Verlust ${cp.loss.toFixed(4)}` : ""}
          </span>
          {cp.jobId && cp.step < cp.total ? (
            <span className="g-value">
              <button type="button" className="g-button" disabled={cmd.pending} onClick={() => continueRun(cp, false)}>
                Fortsetzen
              </button>
              <button type="button" className="g-button" disabled={cmd.pending} onClick={() => continueRun(cp, true)}>
                Beenden
              </button>
            </span>
          ) : null}
        </div>
      ))}
      {character.loras.map((l) => (
        <div className="g-line" key={l.key}>
          <span className="g-ellipsis">
            {l.key} · {l.arch}
          </span>
          <span className="g-value">
            <span className="g-badge" data-tone={gate(LORA_GATE, l.status)[1]} title={gate(LORA_GATE, l.status)[3]}>
              {gate(LORA_GATE, l.status)[0]}
            </span>
            {l.active ? (
              <button type="button" className="g-button" disabled={cmd.pending} onClick={() => activate("", l.arch)}>
                Aktiv · aufheben
              </button>
            ) : (
              <button type="button" className="g-button" disabled={cmd.pending || l.status === "GESPERRT"} onClick={() => activate(l.key, l.arch)}>
                Aktiv setzen
              </button>
            )}
          </span>
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
