import { useState, type FormEvent } from "react";
import { useCommand } from "../core/commands";
import { type Influencer } from "../core/generated/darkfluenzer/v1/influencer_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useStateTopic } from "../core/state";

// Influencerin-Pflege an genau einer Komponente (FRONT F4 V1.12 Punkt 12): Block „Modelle und
// Fähigkeiten“, standardmäßig geschlossen, erreichbar aus der Kundenakte und dem Default-Kontakt.
// Speichern nur nach Bestätigung „gilt für alle Kunden von <Name>“ (Befehl 35, CAS, Receipt).

// Produkt (SP5 Schritt 1): feste ID, Art, Workflow (Video: Bild-Workflow + Animation), Kandidaten,
// Höchstlänge, Zusatzleistungen
interface Row {
  id: bigint;
  product: string;
  price: string;
  hd: string;
  kind: string;
  workflow: string;
  finish: string;
  candidates: string;
  duration: string;
  delivery: string;
  original: boolean;
  selfDestruct: boolean;
  deliverable: boolean;
  problems: string[];
}

const WAY_LABEL: Record<string, string> = {
  amazon: "Amazon-Gutschein",
  btc: "Bitcoin",
  usdt: "USDT",
  usdc: "USDC",
  paypal: "PayPal",
};

// Verhaltensprofil (SP4 Schritt 7): nur Zahlen für die Ausführung; Stil und Ton stehen im Promptprofil
const BEHAVIOR: [string, string][] = [
  ["bundle_s", "Bündeln s"],
  ["read_min_s", "Lesen min s"],
  ["read_max_s", "Lesen max s"],
  ["think_min_s", "Bedenken min s"],
  ["think_max_s", "Bedenken max s"],
  ["typing_cps", "Tippen Zeichen/s"],
  ["slow_min_s", "Langsam min s"],
  ["slow_max_s", "Langsam max s"],
  ["pause_after_s", "Pause ab s"],
  ["slow_chance", "Zufällig langsam 0–1"],
  ["night_start_h", "Nacht ab Uhr"],
  ["night_end_h", "Nacht bis Uhr"],
  ["night_min_s", "Nachts min s"],
  ["night_max_s", "Nachts max s"],
  ["readiness_fast", "Nachts zügig ab Kaufbereitschaft"],
  ["max_wait_s", "Vertrösten nach s"],
  ["consolations_per_day", "Vertröstungen je Tag"],
  ["consolation_stock", "Vertröst-Texte vorrätig"],
];

/** Verhaltensprofil der Influencerin (Befehl 53): neue Version, sofort aktiv. */
function BehaviorEditor({ influencer }: { influencer: Influencer }) {
  const cmd = useCommand();
  const saved = Object.fromEntries(BEHAVIOR.map(([k]) => [k, String(influencer.behavior[k] ?? "")]));
  const [values, setValues] = useState<Record<string, string>>(saved);
  const changed = BEHAVIOR.some(([k]) => values[k] !== saved[k]);
  return (
    <div className="g-control-part g-wide">
      <h3>
        Verhalten
        {influencer.behaviorVersion ? ` · Version ${influencer.behaviorVersion}` : " · Startwerte"}
      </h3>
      <div className="g-behavior">
        {BEHAVIOR.map(([key, label]) => (
          <div key={key} className="g-field">
            <label htmlFor={`beh-${influencer.influencerId}-${key}`}>{label}</label>
            <input
              id={`beh-${influencer.influencerId}-${key}`}
              inputMode="decimal"
              value={values[key]}
              onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <button
        type="button"
        className="g-button"
        disabled={cmd.pending || !changed}
        onClick={() =>
          void cmd.run(
            {
              case: "behaviorUpdate",
              value: {
                influencerId: influencer.influencerId,
                values: Object.fromEntries(BEHAVIOR.map(([k]) => [k, Number(String(values[k]).replace(",", "."))])),
              },
            },
            { done: "Verhalten übernommen." },
          )
        }
      >
        Verhalten übernehmen
      </button>
      {cmd.notice ? (
        <p className="g-note" role="status">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

const euro = (cents: bigint) => (Number(cents) / 100).toFixed(2).replace(".", ",");
const cents = (text: string) => Math.round(Number(text.replace(",", ".").trim()) * 100);

type Props = {
  influencer: Influencer | undefined;
  mediaTitle?: string;
  videoTitle?: string;
};

// Rahmen und Befehl bleiben über das Speichern hinweg bestehen (offen, Bestätigung sichtbar); nur das
// Formular lädt mit jeder neuen Revision die gespeicherten Werte neu.
export function InfluencerBlock(props: Props) {
  const cmd = useCommand();
  const { influencer } = props;
  return (
    <details className="g-fold">
      <summary>
        <span>Influencerin</span>
        <span className="g-fold-hint">{influencer ? influencer.name : "Neue Influencerin"} · gilt für alle Kunden</span>
      </summary>
      <InfluencerForm key={`${influencer?.influencerId ?? "neu"}-${influencer?.revision ?? 0}`} {...props} cmd={cmd} />
    </details>
  );
}

function InfluencerForm({ influencer, mediaTitle, videoTitle, cmd }: Props & { cmd: ReturnType<typeof useCommand> }) {
  const state = useStateTopic(Topic.INFLUENCERS)?.value;
  const characters = useStateTopic(Topic.CHARACTERS)?.value.characters ?? [];
  const [name, setName] = useState(influencer?.name ?? "");
  const [persona, setPersona] = useState(influencer?.persona ?? "");
  const [notice, setNotice] = useState(influencer?.aiNotice ?? "");
  const [character, setCharacter] = useState(influencer?.characterId ? String(influencer.characterId) : "");
  // Schalter (C5.1): Text-KI und automatische Antworten
  const [textAi, setTextAi] = useState(influencer?.textAi ?? false);
  const [autoReplies, setAutoReplies] = useState(influencer?.autoReplies ?? false);
  const [rows, setRows] = useState<Row[]>(() =>
    (influencer?.prices ?? []).map((p) => ({
      id: p.id,
      product: p.product,
      price: euro(p.priceCents),
      hd: euro(p.hdSurchargeCents),
      kind: p.kind || "image",
      workflow: p.workflow,
      finish: p.finishWorkflow,
      candidates: String(p.candidates || 1),
      duration: p.maxDurationS ? String(p.maxDurationS) : "",
      delivery: p.maxDeliveryS ? String(Math.round(p.maxDeliveryS / 60)) : "",
      original: p.originalFile,
      selfDestruct: p.selfDestruct,
      deliverable: p.deliverable,
      problems: [...p.problems],
    })),
  );
  const [ways, setWays] = useState<string[]>(influencer?.paymentWays.length ? [...influencer.paymentWays] : ["amazon"]);
  const [valid, setValid] = useState(influencer?.offerValidMin ? String(influencer.offerValidMin) : "");
  // Sperrzeit nach einer Ablehnung (SP5 Schritt 2)
  const [cooldown, setCooldown] = useState(influencer?.offerCooldownMin ? String(influencer.offerCooldownMin) : "");
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const imageWfs = workflows.filter((w) => w.kind === "image" && !w.training);
  const videoWfs = workflows.filter((w) => w.kind === "video" && w.params.some((x) => x.upload && x.name === "image"));
  const [confirm, setConfirm] = useState(false);
  const invalid = rows.some((r) => !r.product.trim() || !(cents(r.price) > 0) || !(cents(r.hd || "0") >= 0));
  const label = influencer ? influencer.name : name.trim() || "Neue Influencerin";

  function edit(i: number, field: keyof Row, value: string | boolean) {
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
          prices: rows.map((r) => ({
            id: r.id,
            product: r.product.trim(),
            priceCents: BigInt(cents(r.price)),
            hdSurchargeCents: BigInt(cents(r.hd || "0")),
            kind: r.kind,
            workflow: r.workflow,
            finishWorkflow: r.kind === "video" ? r.finish : "",
            candidates: Number(r.candidates) || 1,
            maxDurationS: r.kind === "video" ? Number(r.duration) || 0 : 0,
            maxDeliveryS: (Number(r.delivery) || 0) * 60,
            originalFile: r.original,
            selfDestruct: r.selfDestruct,
          })),
          paymentWays: ways,
          offerValidMin: Number(valid) || 0,
          offerCooldownMin: Number(cooldown) || 0,
        },
      },
      { done: "Profil gespeichert – gilt für alle Kunden." },
    );
  }

  return (
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
          <div key={String(r.id) || `neu-${i}`} className="g-product">
            <div className="g-price-row">
              <input aria-label="Produkt" placeholder="Produkt" value={r.product} onChange={(e) => edit(i, "product", e.target.value)} />
              <input aria-label="Preis in €" placeholder="Preis €" inputMode="decimal" value={r.price} onChange={(e) => edit(i, "price", e.target.value)} />
              <input
                aria-label="HD-Aufschlag in €"
                placeholder="HD-Aufschlag €"
                inputMode="decimal"
                value={r.hd}
                onChange={(e) => edit(i, "hd", e.target.value)}
              />
              <button type="button" className="g-button" aria-label="Position entfernen" onClick={() => setRows(rows.filter((_, n) => n !== i))}>
                ×
              </button>
            </div>
            <div className="g-product-row">
              <select aria-label={`Art ${r.product || i + 1}`} value={r.kind} onChange={(e) => edit(i, "kind", e.target.value)}>
                <option value="image">Bild</option>
                <option value="video">Video</option>
              </select>
              <select aria-label={`Workflow ${r.product || i + 1}`} value={r.workflow} onChange={(e) => edit(i, "workflow", e.target.value)}>
                <option value="">Workflow wählen</option>
                {imageWfs.map((w) => (
                  <option key={w.key} value={w.key}>
                    {w.title}
                  </option>
                ))}
              </select>
              {r.kind === "video" ? (
                <>
                  <select aria-label={`Animation ${r.product || i + 1}`} value={r.finish} onChange={(e) => edit(i, "finish", e.target.value)}>
                    <option value="">Animation wählen</option>
                    {videoWfs.map((w) => (
                      <option key={w.key} value={w.key}>
                        {w.title}
                      </option>
                    ))}
                  </select>
                  <label className="g-product-num">
                    Höchstlänge s
                    <input
                      aria-label={`Höchstlänge s ${r.product || i + 1}`}
                      inputMode="decimal"
                      value={r.duration}
                      onChange={(e) => edit(i, "duration", e.target.value)}
                    />
                  </label>
                </>
              ) : null}
              <label className="g-product-num">
                Kandidaten
                <input
                  aria-label={`Kandidaten ${r.product || i + 1}`}
                  inputMode="numeric"
                  value={r.candidates}
                  onChange={(e) => edit(i, "candidates", e.target.value)}
                />
              </label>
              <label className="g-product-num">
                Lieferzeit max. min
                <input
                  aria-label={`Lieferzeit max. min ${r.product || i + 1}`}
                  inputMode="numeric"
                  value={r.delivery}
                  onChange={(e) => edit(i, "delivery", e.target.value)}
                />
              </label>
              <label className="g-switch">
                <input type="checkbox" checked={r.original} onChange={(e) => edit(i, "original", e.target.checked)} />
                Originaldatei
              </label>
              <label className="g-switch">
                <input type="checkbox" checked={r.selfDestruct} onChange={(e) => edit(i, "selfDestruct", e.target.checked)} />
                Selbstlöschend
              </label>
            </div>
            {r.id ? (
              r.deliverable ? (
                <small className="g-ok-text">lieferbar</small>
              ) : (
                <small className="g-note">nicht lieferbar: {r.problems.join("; ")}</small>
              )
            ) : null}
          </div>
        ))}
        {rows.length === 0 ? <small>Noch keine Preise.</small> : null}
        <button
          type="button"
          className="g-button"
          onClick={() =>
            setRows([
              ...rows,
              {
                id: 0n,
                product: "",
                price: "",
                hd: "0",
                kind: "image",
                workflow: "",
                finish: "",
                candidates: "1",
                duration: "",
                delivery: "",
                original: false,
                selfDestruct: false,
                deliverable: false,
                problems: [],
              },
            ])
          }
        >
          Position hinzufügen
        </button>
        <h3>Zahlungswege und Gültigkeit</h3>
        {Object.keys(WAY_LABEL).map((w) => {
          const available = state?.influencers[0]?.paymentWaysAvailable.includes(w) ?? w === "amazon";
          return (
            <label key={w} className="g-switch">
              <input type="checkbox" checked={ways.includes(w)} onChange={(e) => setWays(e.target.checked ? [...ways, w] : ways.filter((x) => x !== w))} />
              {WAY_LABEL[w]}
              {available ? "" : " (nicht eingerichtet)"}
            </label>
          );
        })}
        <div className="g-field">
          <label htmlFor={`inf-valid-${label}`}>Angebot gültig (Minuten, leer = Vorgabe)</label>
          <input id={`inf-valid-${label}`} inputMode="numeric" value={valid} onChange={(e) => setValid(e.target.value)} />
        </div>
        <div className="g-field">
          <label htmlFor={`inf-cooldown-${label}`}>Sperrzeit nach Ablehnung (Minuten, leer = keine)</label>
          <input id={`inf-cooldown-${label}`} inputMode="numeric" value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
        </div>
      </div>
      {influencer ? <BehaviorEditor key={`${influencer.influencerId}-${influencer.behaviorVersion}`} influencer={influencer} /> : null}
      <div className="g-control-part g-wide">
        <h3>Modelle und Fähigkeiten</h3>
        <dl className="g-params">
          {(
            [
              ["Text-KI", textAi ? (autoReplies ? "an · antwortet automatisch" : "an · Entwürfe") : "aus"],
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
  );
}
