import { useState, type FormEvent } from "react";
import { useCommand } from "../core/commands";
import { type Influencer } from "../core/generated/darkfluenzer/v1/influencer_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useStateTopic } from "../core/state";

// Influencerin-Pflege an genau einer Komponente (FRONT F4 V1.12 Punkt 12): Block „Modelle und
// Fähigkeiten“, standardmäßig geschlossen, erreichbar aus der Kundenakte und dem Default-Kontakt.
// Speichern nur nach Bestätigung „gilt für alle Kunden von <Name>“ (Befehl 35, CAS, Receipt).

interface Row {
  product: string;
  price: string;
  hd: string;
}

const euro = (cents: bigint) => (Number(cents) / 100).toFixed(2).replace(".", ",");
const cents = (text: string) => Math.round(Number(text.replace(",", ".").trim()) * 100);

export function InfluencerBlock({ influencer, mediaTitle, videoTitle }: { influencer: Influencer | undefined; mediaTitle?: string; videoTitle?: string }) {
  const state = useStateTopic(Topic.INFLUENCERS)?.value;
  const characters = useStateTopic(Topic.CHARACTERS)?.value.characters ?? [];
  const cmd = useCommand();
  const [name, setName] = useState(influencer?.name ?? "");
  const [persona, setPersona] = useState(influencer?.persona ?? "");
  const [notice, setNotice] = useState(influencer?.aiNotice ?? "");
  const [character, setCharacter] = useState(influencer?.characterId ? String(influencer.characterId) : "");
  // Schalter (C5.1): Text-KI und automatische Antworten
  const [textAi, setTextAi] = useState(influencer?.textAi ?? false);
  const [autoReplies, setAutoReplies] = useState(influencer?.autoReplies ?? false);
  const [rows, setRows] = useState<Row[]>(() =>
    (influencer?.prices ?? []).map((p) => ({ product: p.product, price: euro(p.priceCents), hd: euro(p.hdSurchargeCents) })),
  );
  const [confirm, setConfirm] = useState(false);
  const invalid = rows.some((r) => !r.product.trim() || !(cents(r.price) > 0) || !(cents(r.hd || "0") >= 0));
  const label = influencer ? influencer.name : name.trim() || "Neue Influencerin";

  function edit(i: number, field: keyof Row, value: string) {
    setRows(rows.map((r, n) => (n === i ? { ...r, [field]: value } : r)));
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!confirm) {
      setConfirm(true);
      return;
    }
    setConfirm(false);
    await cmd.run(
      {
        case: "influencerUpdate",
        value: {
          influencerId: influencer?.influencerId ?? 0n,
          revision: influencer?.revision ?? 0n,
          name: name.trim(),
          characterId: character ? BigInt(character) : 0n,
          persona,
          aiNotice: notice,
          textAi,
          autoReplies,
          prices: rows.map((r) => ({ product: r.product.trim(), priceCents: BigInt(cents(r.price)), hdSurchargeCents: BigInt(cents(r.hd || "0")) })),
        },
      },
      { done: "Profil gespeichert – gilt für alle Kunden." },
    );
  }

  return (
    <details className="g-fold">
      <summary>
        <span>Influencerin</span>
        <span className="g-fold-hint">{label} · gilt für alle Kunden</span>
      </summary>
      <form className="g-form g-fold-body" onSubmit={save}>
        <div className="g-control-part g-wide">
          <h3>Profil</h3>
          <div className="g-field">
            <label htmlFor={`inf-name-${label}`}>Name</label>
            <input id={`inf-name-${label}`} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="g-field">
            <label htmlFor={`inf-persona-${label}`}>Persona-/Charaktertext</label>
            <textarea id={`inf-persona-${label}`} rows={4} value={persona} onChange={(e) => setPersona(e.target.value)} />
          </div>
          <div className="g-field">
            <label htmlFor={`inf-notice-${label}`}>KI-Hinweistext (erster Kontakt je Kanal)</label>
            <textarea id={`inf-notice-${label}`} rows={2} value={notice} onChange={(e) => setNotice(e.target.value)} />
          </div>
          <label className="g-switch">
            <input type="checkbox" checked={textAi} onChange={(e) => setTextAi(e.target.checked)} />
            Text-KI
          </label>
          <label className="g-switch">
            <input type="checkbox" checked={autoReplies} disabled={!textAi} onChange={(e) => setAutoReplies(e.target.checked)} />
            Automatische Antworten
          </label>
          <div className="g-field">
            <span>Ehrlichkeitsregel (fest)</span>
            <small>{state?.honestyRule ?? "–"}</small>
          </div>
          <div className="g-field">
            <label htmlFor={`inf-char-${label}`}>Charakterprofil (gepflegt im Reiter ComfyUI)</label>
            <select id={`inf-char-${label}`} value={character} onChange={(e) => setCharacter(e.target.value)}>
              <option value="">Nicht festgelegt</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="g-control-part g-wide">
          <h3>Preisliste</h3>
          {rows.map((r, i) => (
            <div key={i} className="g-price-row">
              <input aria-label="Produkt" placeholder="Produkt" value={r.product} onChange={(e) => edit(i, "product", e.target.value)} />
              <input aria-label="Preis in €" placeholder="Preis €" inputMode="decimal" value={r.price} onChange={(e) => edit(i, "price", e.target.value)} />
              <input aria-label="HD-Aufschlag in €" placeholder="HD-Aufschlag €" inputMode="decimal" value={r.hd} onChange={(e) => edit(i, "hd", e.target.value)} />
              <button type="button" className="g-button" aria-label="Position entfernen" onClick={() => setRows(rows.filter((_, n) => n !== i))}>
                ×
              </button>
            </div>
          ))}
          {rows.length === 0 ? <small>Noch keine Preise.</small> : null}
          <button type="button" className="g-button" onClick={() => setRows([...rows, { product: "", price: "", hd: "0" }])}>
            Position hinzufügen
          </button>
        </div>
        <div className="g-control-part g-wide">
          <h3>Modelle und Fähigkeiten</h3>
          <dl className="g-params">
            {(
              [
                ["Text-KI", "nicht angeschlossen (KI-Instanz folgt)"],
                ["Foto", mediaTitle || "–"],
                ["Video", videoTitle || "–"],
                ["Stimme", "nicht angeschlossen"],
              ] as const
            ).map(([dt, dd]) => (
              <div key={dt}>
                <dt>{dt}</dt>
                <dd>{dd}</dd>
              </div>
            ))}
          </dl>
        </div>
        {confirm ? (
          <div className="g-actions g-wide">
            <button type="submit" className="g-button g-primary" disabled={cmd.pending}>
              Gilt für alle Kunden von {name.trim() || "dieser Influencerin"} – speichern
            </button>
            <button type="button" className="g-button" onClick={() => setConfirm(false)}>
              Abbrechen
            </button>
          </div>
        ) : (
          <button type="submit" className="g-button g-primary g-block g-wide" disabled={cmd.pending || !name.trim() || invalid}>
            {influencer ? "Profil speichern" : "Influencerin anlegen"}
          </button>
        )}
        {cmd.notice ? (
          <p className="g-note g-wide" role="alert">
            {cmd.notice}
          </p>
        ) : null}
      </form>
    </details>
  );
}
