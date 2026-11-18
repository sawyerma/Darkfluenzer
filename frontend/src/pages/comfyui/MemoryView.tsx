import { useEffect, useState } from "react";
import { useCommand } from "../../core/commands";
import type { MemoryEntry, MemoryPage } from "../../core/generated/darkfluenzer/v1/memory_pb";
import type { Influencer } from "../../core/generated/darkfluenzer/v1/influencer_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { fetchMemory } from "../../core/memory";
import { useEventTopic } from "../../core/state";

const LEVELS: readonly [string, string][] = [
  ["customer", "Kundengedächtnis"],
  ["memo", "Gesprächsmemo"],
  ["event", "Ereignis"],
  ["self", "Eigene Aussage"],
];
const STATUS: Record<string, string> = { active: "aktiv", replaced: "ersetzt", deleted: "gelöscht" };

function when(ms: bigint): string {
  return new Date(Number(ms)).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

/** Gedächtnis der Studio-Sitzung (SP4 Schritt 5, B5.3): Einträge je Ebene mit Quelle, Zeit, Status;
 *  Notiz, Korrektur (Verlauf bleibt) und Löschen über Befehl 52; Kontextinspektor zeigt, welche Einträge
 *  für eine Nachricht in den nächsten Lauf gingen und warum. */
export function MemoryView({ influencer, live }: { influencer: Influencer; live: boolean }) {
  const cmd = useCommand();
  const changes = useEventTopic(Topic.MEMORY_CHANGED);
  const session = influencer.studioSession;
  const [page, setPage] = useState<MemoryPage | null>(null);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState("");
  const [selected, setSelected] = useState<Map<bigint, string>>(new Map());
  const [level, setLevel] = useState("customer");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<{ id: bigint; text: string } | null>(null);
  const [confirm, setConfirm] = useState<bigint | null>(null);
  const count = changes?.items.length ?? 0;

  useEffect(() => {
    let gone = false;
    fetchMemory("studio", influencer.influencerId, session)
      .then((p) => !gone && (setPage(p), setError("")))
      .catch((e: unknown) => !gone && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      gone = true;
    };
  }, [influencer.influencerId, session, count]);

  async function edit(value: { memoryId?: bigint; level?: string; text?: string; delete?: boolean }, done: string) {
    return cmd.run(
      { case: "memoryEdit", value: { scope: "studio", ownerId: influencer.influencerId, session, ...value } },
      { done },
    );
  }

  async function inspect() {
    const p = await fetchMemory("studio", influencer.influencerId, session, probe);
    setSelected(new Map(p.selected.map((s) => [s.memoryId, s.reason])));
  }

  const entries = page?.entries ?? [];
  const active = entries.filter((e) => e.status === "active");
  const history = entries.filter((e) => e.status !== "active");
  const row = (e: MemoryEntry) => (
    <div key={String(e.memoryId)} className="g-memory" data-status={e.status}>
      {editing?.id === e.memoryId ? (
        <span className="g-memory-edit">
          <input aria-label="Korrigierter Text" value={editing.text} onChange={(ev) => setEditing({ id: e.memoryId, text: ev.target.value })} />
          <button
            type="button"
            className="g-button g-primary"
            disabled={!live || cmd.pending || !editing.text.trim()}
            onClick={async () => (await edit({ memoryId: e.memoryId, text: editing.text }, "Korrigiert.")) && setEditing(null)}
          >
            Speichern
          </button>
          <button type="button" className="g-button" onClick={() => setEditing(null)}>
            Abbrechen
          </button>
        </span>
      ) : (
        <span className="g-memory-text">
          {selected.has(e.memoryId) ? (
            <span className="g-badge" data-tone="ok">
              {selected.get(e.memoryId) === "Treffer" ? "TREFFER" : "JÜNGSTE"}
            </span>
          ) : null}
          #{String(e.memoryId)} {e.text}
        </span>
      )}
      <small>
        {e.source || "–"} · {when(e.createdMs)} · {STATUS[e.status] ?? e.status}
        {e.replacedBy ? ` → #${String(e.replacedBy)}` : ""}
      </small>
      {e.status === "active" && editing?.id !== e.memoryId ? (
        <span className="g-actions">
          <button type="button" className="g-button" disabled={!live} onClick={() => setEditing({ id: e.memoryId, text: e.text })}>
            Korrigieren
          </button>
          {confirm === e.memoryId ? (
            <button
              type="button"
              className="g-button g-danger"
              disabled={!live || cmd.pending}
              onClick={async () => (await edit({ memoryId: e.memoryId, delete: true }, "Gelöscht.")) && setConfirm(null)}
            >
              Wirklich löschen
            </button>
          ) : (
            <button type="button" className="g-button" disabled={!live} onClick={() => setConfirm(e.memoryId)}>
              Löschen
            </button>
          )}
        </span>
      ) : null}
    </div>
  );

  return (
    <div className="g-form">
      <p className="g-note g-wide">Gedächtnis · Sitzung {session}</p>
      <div className="g-field">
        <label htmlFor="mem-level">Ebene</label>
        <select id="mem-level" value={level} onChange={(e) => setLevel(e.target.value)}>
          {LEVELS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="g-field">
        <label htmlFor="mem-note">Notiz</label>
        <input id="mem-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <button
        type="button"
        className="g-button g-wide"
        disabled={!live || cmd.pending || !note.trim()}
        onClick={async () => (await edit({ level, text: note }, "Notiz gespeichert.")) && setNote("")}
      >
        Notiz manuell hinzufügen
      </button>
      {cmd.notice ? (
        <p className="g-note g-wide" role="status">
          {cmd.notice}
        </p>
      ) : null}
      <div className="g-field g-wide">
        <label htmlFor="mem-probe">Kontextinspektor · Nachricht</label>
        <span className="g-memory-edit">
          <input id="mem-probe" value={probe} placeholder="Nachricht, für die die Auswahl gezeigt wird" onChange={(e) => setProbe(e.target.value)} />
          <button type="button" className="g-button" disabled={!probe.trim()} onClick={() => void inspect()}>
            Auswahl zeigen
          </button>
        </span>
      </div>
      {error ? <p className="g-note g-error g-wide">{error}</p> : null}
      {LEVELS.map(([key, label]) => {
        const items = active.filter((e) => e.level === key);
        return (
          <div key={key} className="g-field g-wide">
            <label>
              {label} · {items.length}
            </label>
            {items.length ? items.map(row) : <small>Keine Einträge.</small>}
          </div>
        );
      })}
      {history.length ? (
        <details className="g-checks g-wide">
          <summary>Verlauf · {history.length} ersetzt oder gelöscht</summary>
          {history.map(row)}
        </details>
      ) : null}
    </div>
  );
}
