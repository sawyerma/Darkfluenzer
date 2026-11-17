import type { Character } from "../../core/generated/darkfluenzer/v1/character_pb";
import { type FormEvent, useEffect, useState } from "react";
import { PHOTO_STATUS, WORKFLOW_TONE } from "./common";
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

/** Charakter (Steuerung, F7.5): Profil wählen, anlegen, umbenennen; bei Trainingsworkflows den
 *  Trainingsdatenordner übernehmen (Befehl 25, CAS über die Profilrevision). */
export function CharacterControl({ training, list, current, choose }: { training: boolean } & ReturnType<typeof useCharacter>) {
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
export function TrainingFolder({ character }: { character: Character | undefined }) {
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
