import { useEffect, useState } from "react";
import { useCommand } from "../../core/commands";
import type { Influencer, PersonaVersion } from "../../core/generated/darkfluenzer/v1/influencer_pb";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useStateTopic } from "../../core/state";

// KI-Studio (FRONTEND §3.4, F7.9, Backend SP4): innere Ansichten ändern nur die Mitte. Persona ist
// das versionierte Promptprofil je Influencerin (SP4 Schritt 2, Befehle 35/68); Chat-Test,
// Gedächtnis und Vergleich brauchen den registrierten Sprachworkflow (SP4 Schritt 1 und 5) und
// bleiben bis dahin gesperrt – keine fingierten Ergebnisse.

type View = "chat" | "persona" | "memory" | "compare";

const VIEWS: readonly [View, string, string][] = [
  ["chat", "Chat-Test", "Sprachworkflow noch nicht eingerichtet (SP4 Schritt 1)."],
  ["persona", "Persona", ""],
  ["memory", "Gedächtnis", "Gedächtnis folgt mit SP4 Schritt 5."],
  ["compare", "Vergleich", "Vergleich braucht den Sprachworkflow (SP4 Schritt 1)."],
];

function versionDate(v: PersonaVersion): string {
  return new Date(Number(v.createdMs)).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

export function KiStudio() {
  const [view, setView] = useState<View>("persona");
  const blocked = VIEWS.find(([v]) => v === view)?.[2] ?? "";
  return (
    <div className="g-workmain">
      <div className="g-subtabs" role="tablist" aria-label="KI-Studio">
        {VIEWS.map(([v, label]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}>
            {label}
          </button>
        ))}
      </div>
      {view === "persona" ? <PersonaView /> : <p className="g-note">{blocked}</p>}
    </div>
  );
}

function PersonaView() {
  const state = useStateTopic(Topic.INFLUENCERS)?.value;
  const influencers = state?.influencers ?? [];
  const [chosen, setChosen] = useState<bigint | null>(null);
  const current = influencers.find((i) => i.influencerId === chosen) ?? influencers[0];
  if (!state) return <p className="g-note">Lädt …</p>;
  if (!current) return <p className="g-note">Noch keine Influencerin angelegt (Nachrichten → Influencerin-Block).</p>;
  return (
    <>
      {influencers.length > 1 ? (
        <div className="g-field">
          <label htmlFor="ki-figure">Influencerin</label>
          <select id="ki-figure" value={String(current.influencerId)} onChange={(e) => setChosen(BigInt(e.target.value))}>
            {influencers.map((i) => (
              <option key={String(i.influencerId)} value={String(i.influencerId)}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      <ProfileEditor key={`${current.influencerId}-${current.personaActive}`} influencer={current} blocks={state.profileBlocks} honesty={state.honestyRule} />
    </>
  );
}

function ProfileEditor({ influencer, blocks, honesty }: { influencer: Influencer; blocks: readonly { key: string; label: string }[]; honesty: string }) {
  const cmd = useCommand();
  const versions = influencer.personaVersions;
  const active = versions.find((v) => v.version === influencer.personaActive);
  const [base, setBase] = useState<PersonaVersion | undefined>(active);
  const [text, setText] = useState<Record<string, string>>(() => ({ ...(active?.blocks ?? {}) }));
  const [note, setNote] = useState("");
  const [compare, setCompare] = useState<PersonaVersion | null>(null);
  useEffect(() => setCompare(null), [influencer.personaActive]);
  const changed = blocks.some((b) => (text[b.key] ?? "").trim() !== (base?.blocks[b.key] ?? "").trim());

  function load(v: PersonaVersion) {
    setBase(v);
    setText({ ...v.blocks });
  }

  async function save(activate: boolean) {
    const done = await cmd.run(
      {
        case: "influencerUpdate",
        value: {
          influencerId: influencer.influencerId,
          revision: influencer.revision,
          name: influencer.name,
          characterId: influencer.characterId,
          persona: influencer.persona,
          aiNotice: influencer.aiNotice,
          prices: influencer.prices,
          profile: { blocks: Object.fromEntries(Object.entries(text).filter(([, v]) => v.trim())), params: active?.params ?? {}, note, activate },
        },
      },
      { done: activate ? "Gespeichert und aktiviert." : "Als neue Version gespeichert." },
    );
    if (done) setNote("");
  }

  async function activate(v: PersonaVersion) {
    await cmd.run(
      { case: "promptProfileActivate", value: { influencerId: influencer.influencerId, version: v.version } },
      { done: `Version ${v.version} aktiv.` },
    );
  }

  return (
    <div className="g-form">
      <p className="g-note g-wide">
        {active ? `Aktiv: Version ${active.version}` : "Noch keine aktive Version"}
        {base && base.version !== active?.version ? ` · im Editor: Version ${base.version}` : ""}
      </p>
      {blocks.map((b) => (
        <div key={b.key} className="g-field g-wide">
          <label htmlFor={`ki-${b.key}`}>{b.label}</label>
          <textarea id={`ki-${b.key}`} rows={b.key === "persona" || b.key === "system_prompt" ? 5 : 3} value={text[b.key] ?? ""} onChange={(e) => setText({ ...text, [b.key]: e.target.value })} />
        </div>
      ))}
      <div className="g-field g-wide">
        <label>Ehrlichkeitsblock (fest im Sprachworkflow)</label>
        <small>{honesty}</small>
      </div>
      <div className="g-field g-wide">
        <label htmlFor="ki-note">Notiz zur Version</label>
        <input id="ki-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <div className="g-actions g-wide">
        <button type="button" className="g-button" disabled={cmd.pending || !changed} onClick={() => void save(false)}>
          Persona übernehmen
        </button>
        <button type="button" className="g-button g-primary" disabled={cmd.pending || !changed} onClick={() => void save(true)}>
          Übernehmen und aktivieren
        </button>
        <button type="button" className="g-button" disabled title="Chat-Test braucht den Sprachworkflow (SP4 Schritt 1)">
          Im Test ausführen
        </button>
      </div>
      {cmd.notice ? (
        <p className="g-note g-wide" role="status">
          {cmd.notice}
        </p>
      ) : null}
      <div className="g-field g-wide">
        <label>Versionen</label>
        {[...versions].reverse().map((v) => (
          <span key={v.version} className="g-version-row">
            <span className="g-ellipsis">
              Version {v.version} · {versionDate(v)}
              {v.note ? ` · ${v.note}` : ""}
            </span>
            {v.version === influencer.personaActive ? (
              <span className="g-badge" data-tone="ok">
                AKTIV
              </span>
            ) : (
              <span />
            )}
            <button type="button" className="g-button" onClick={() => load(v)}>
              Laden
            </button>
            <button type="button" className="g-button" disabled={!active || v.version === active.version} onClick={() => setCompare(compare?.version === v.version ? null : v)}>
              Vergleichen
            </button>
            <button type="button" className="g-button" disabled={cmd.pending || v.version === influencer.personaActive} onClick={() => void activate(v)}>
              {active && v.version < active.version ? "Zurücksetzen" : "Aktivieren"}
            </button>
          </span>
        ))}
        {versions.length === 0 ? <small>Noch keine Version gespeichert.</small> : null}
      </div>
      {compare && active ? (
        <div className="g-field g-wide">
          <label>
            Version {compare.version} gegen aktive Version {active.version}
          </label>
          {blocks
            .filter((b) => (compare.blocks[b.key] ?? "") !== (active.blocks[b.key] ?? ""))
            .map((b) => (
              <details key={b.key} className="g-details" open>
                <summary>{b.label}</summary>
                <p className="g-diff">
                  <small>Version {compare.version}</small> {compare.blocks[b.key] || "(leer)"}
                </p>
                <p className="g-diff">
                  <small>Version {active.version}</small> {active.blocks[b.key] || "(leer)"}
                </p>
              </details>
            ))}
        </div>
      ) : null}
    </div>
  );
}
