import { AGE_MARK, NOTICE } from "./common";
import type { ChannelIdentity, CustomerSummary } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { EUR } from "./Stream";
import type { Influencer } from "../../core/generated/darkfluenzer/v1/influencer_pb";
import { InfluencerBlock } from "../InfluencerBlock";
import { PLATFORMS, PLATFORM_LABEL, handleLabel } from "../../core/channels";
import { type ReactNode, useState } from "react";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useCommand } from "../../core/commands";
import { useStateTopic } from "../../core/state";

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Rechte Spalte für Kunden: Identität mit Alter und KI-Hinweis je Kanal, Angebot, KI-Steuerung. */
export function CustomerPanel({ customer, identities }: { customer: CustomerSummary; identities: readonly ChannelIdentity[] }) {
  // Claras Konten gehören zu genau einer Figur; die Zuordnung je Kanalkonto folgt mit C5
  const figure = useStateTopic(Topic.INFLUENCERS)?.value.influencers[0];
  const accounts = identities.filter((i, n) => identities.findIndex((x) => x.identityId === i.identityId) === n);
  const active = PLATFORMS.filter((p) => customer.platforms.includes(p)).map((p) => PLATFORM_LABEL[p]);
  return (
    <>
      <div className="g-line g-head">
        <h2>Kundenakte · {customer.customerNo}</h2>
        <span className="g-badge">KUNDE</span>
      </div>
      <div className="g-control-part">
        <h3>Identität</h3>
        <dl className="g-params">
          <Row label="Kunde">{customer.displayName || "–"}</Row>
          <Row label="Kundennummer">{customer.customerNo}</Row>
          <Row label="Aktive Kanäle">{active.join(" / ") || "–"}</Row>
        </dl>
        <AgeMark customer={customer} />
        {accounts.map((i) => (
          <div key={String(i.identityId)} className="g-stack">
            <span className="g-between">
              <span className="g-ellipsis">
                <span className="g-ptag" data-platform={i.platform}>
                  {PLATFORM_LABEL[i.platform] ?? i.platform}
                </span>{" "}
                {handleLabel(i.handle) || "ohne Benutzernamen"}
              </span>
              <span className="g-badge" data-tone={i.verified ? "ok" : "warn"}>
                {i.verified ? "VERIFIZIERT" : "NICHT VERIFIZIERT"}
              </span>
            </span>
            <small className="g-mono">
              ID {i.platformUserId}
              {i.account ? ` · Konto ${i.account}` : ""}
            </small>
            <AiNotice customer={customer} identity={i} />
            {i.conversationId ? <ConversationMode identity={i} /> : null}
            <MakeDefault customer={customer} identity={i} />
          </div>
        ))}
      </div>
      <OfferForm customer={customer} identities={accounts} figure={figure} />
      <div className="g-control-part">
        <h3>KI-Steuerung</h3>
        <dl className="g-params">
          <Row label="Influencerin">{figure?.name ?? "nicht festgelegt"}</Row>
        </dl>
        {figure ? (
          <InfluencerBlock key={String(figure.influencerId)} influencer={figure} />
        ) : (
          <small>Influencerin im Default-Kontakt anlegen.</small>
        )}
      </div>
    </>
  );
}

/** Angebot aus der Preisliste (Befehl 46, V0 §8.4 Punkt 3): nur bei Angabe ≥ 18 und gesendetem
 *  KI-Hinweis über den gewählten Kanal; Beträge und Zahlungswege setzt das Backend. */
function OfferForm({
  customer,
  identities,
  figure,
}: {
  customer: CustomerSummary;
  identities: readonly ChannelIdentity[];
  figure: Influencer | undefined;
}) {
  const cmd = useCommand();
  const channels = identities.filter((i) => i.conversationId !== 0n);
  const [identityId, setIdentityId] = useState(channels[0]?.identityId ?? 0n);
  const [position, setPosition] = useState(0);
  const [hd, setHd] = useState(false);
  const [note, setNote] = useState("");
  // Wunsch als Bildbeschreibung: Prompt der Produktion nach Zahlung (SP5 Schritt 6)
  const [wish, setWish] = useState("");
  const ident = channels.find((i) => i.identityId === identityId) ?? channels[0];
  const item = figure?.prices[position];
  const deliverable = item?.deliverable ?? false;
  const total = item ? item.priceCents + (hd ? item.hdSurchargeCents : 0n) : 0n;
  const reason = !figure
    ? "Influencerin-Profil fehlt"
    : figure.prices.length === 0
      ? "Preisliste der Influencerin ist leer"
      : customer.ageMark === "under_18"
        ? "Akte gesperrt (minderjährig vermutet)"
        : !ident
          ? "Noch keine Konversation"
          : ident.aiNotice !== "sent"
            ? "Erst den KI-Hinweis über diesen Kanal senden"
            : !deliverable
              ? `Nicht lieferbar: ${item?.problems.join("; ") || "unbekannt"}`
              : "";

  async function send() {
    if (reason || !ident || !figure) return;
    const done = await cmd.run(
      {
        case: "createOffer",
        value: {
          customerId: customer.customerId,
          identityId: ident.identityId,
          conversationId: ident.conversationId,
          revision: ident.revision,
          influencerId: figure.influencerId,
          position,
          productId: item?.id ?? 0n,
          hd,
          note: note.trim(),
          wish: wish.trim(),
        },
      },
      { done: "Angebot gesendet." },
    );
    if (done) {
      setNote("");
      setWish("");
      setHd(false);
    }
  }

  return (
    <div className="g-control-part">
      <h3>Angebot</h3>
      {channels.length > 1 ? (
        <div className="g-field">
          <label htmlFor={`offer-ch-${customer.customerId}`}>Kanal</label>
          <select
            id={`offer-ch-${customer.customerId}`}
            className="g-input"
            value={String(ident?.identityId ?? "")}
            onChange={(e) => setIdentityId(BigInt(e.target.value))}
          >
            {channels.map((i) => (
              <option key={String(i.identityId)} value={String(i.identityId)}>
                {PLATFORM_LABEL[i.platform] ?? i.platform} · {handleLabel(i.handle) || i.platformUserId}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {figure && figure.prices.length > 0 ? (
        <>
          <div className="g-field">
            <label htmlFor={`offer-pos-${customer.customerId}`}>Preisliste</label>
            <select
              id={`offer-pos-${customer.customerId}`}
              className="g-input"
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
            >
              {figure.prices.map((p, n) => (
                <option key={String(p.id) || n} value={n}>
                  {p.product} · {EUR.format(Number(p.priceCents) / 100)}
                  {p.deliverable ? "" : " · nicht lieferbar"}
                </option>
              ))}
            </select>
          </div>
          <label className="g-switch">
            <input type="checkbox" checked={hd} onChange={(e) => setHd(e.target.checked)} />
            HD (+{EUR.format(Number(item?.hdSurchargeCents ?? 0n) / 100)})
          </label>
          <div className="g-field">
            <label htmlFor={`offer-note-${customer.customerId}`}>Persönlicher Satz (optional)</label>
            <textarea
              id={`offer-note-${customer.customerId}`}
              className="g-input"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <div className="g-field">
            <label htmlFor={`offer-wish-${customer.customerId}`}>Wunsch (Bildbeschreibung für die Produktion)</label>
            <textarea
              id={`offer-wish-${customer.customerId}`}
              className="g-input"
              rows={2}
              value={wish}
              onChange={(e) => setWish(e.target.value)}
            />
          </div>
        </>
      ) : null}
      <span className="g-between">
        <strong>{total ? EUR.format(Number(total) / 100) : "–"}</strong>
        <button type="button" className="g-button g-primary" disabled={Boolean(reason) || cmd.pending} onClick={() => void send()}>
          Angebot senden
        </button>
      </span>
      <small>{reason || "Faktenblock mit Lieferzeit vom Backend; ohne Wunsch startet die Produktion nicht automatisch."}</small>
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

/** Altersangabe der Akte (Befehl 44): Standard „Alter unklar“, sperrt Angebote bis „Angabe ≥ 18“. */
function AgeMark({ customer }: { customer: CustomerSummary }) {
  const cmd = useCommand();
  const [mark, setMark] = useState(customer.ageMark || "unclear");
  return (
    <div className="g-field">
      <label htmlFor={`age-${customer.customerId}`}>Alter</label>
      <span className="g-between">
        <select id={`age-${customer.customerId}`} className="g-input" value={mark} onChange={(e) => setMark(e.target.value)}>
          {AGE_MARK.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="g-button"
          disabled={cmd.pending || mark === (customer.ageMark || "unclear")}
          onClick={() => void cmd.run({ case: "customerAgeMark", value: { customerId: customer.customerId, mark } }, { done: "Alter übernommen." })}
        >
          Übernehmen
        </button>
      </span>
      {mark === "under_18" ? <small>Gesperrt: keine KI-Antwort, kein Angebot.</small> : null}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

// Modus der Konversation (SP4 Schritt 6): KI antwortet, nur Entwurf, Betreiber
const MODES: [string, string][] = [
  ["auto", "KI antwortet"],
  ["draft", "Nur Entwurf"],
  ["manual", "Betreiber"],
];

/** Modus je Konversation (Befehl 54 set_mode); eine Nachricht vom Handy setzt „Betreiber“. */
function ConversationMode({ identity }: { identity: ChannelIdentity }) {
  const cmd = useCommand();
  const id = `mode-${identity.identityId}`;
  return (
    <div className="g-field">
      <label htmlFor={id}>Modus</label>
      <select
        id={id}
        className="g-input"
        value={identity.mode || "auto"}
        disabled={cmd.pending}
        onChange={(e) =>
          void cmd.run({ case: "outboxControl", value: { conversationId: identity.conversationId, action: "set_mode", mode: e.target.value } })
        }
      >
        {MODES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      {cmd.notice ? <small role="alert">{cmd.notice}</small> : null}
    </div>
  );
}

/** KI-Hinweis je Kanalidentität (Befehl 45, Regel 12 b): genau einmal; Status aus der Nachricht. */
function AiNotice({ customer, identity }: { customer: CustomerSummary; identity: ChannelIdentity }) {
  const cmd = useCommand();
  return (
    <span className="g-between">
      <small>KI-Hinweis: {identity.aiNotice ? (NOTICE[identity.aiNotice] ?? identity.aiNotice) : "noch nicht gesendet"}</small>
      {identity.aiNotice && identity.aiNotice !== "failed" ? null : (
        <button
          type="button"
          className="g-button"
          disabled={cmd.pending}
          onClick={() =>
            void cmd.run(
              { case: "sendAiNotice", value: { customerId: customer.customerId, identityId: identity.identityId } },
              { done: "KI-Hinweis eingereiht." },
            )
          }
        >
          {identity.aiNotice === "failed" ? "KI-Hinweis erneut senden" : "KI-Hinweis senden"}
        </button>
      )}
      {cmd.notice ? <small role="alert">{cmd.notice}</small> : null}
    </span>
  );
}

/** Absender dieser Kanalidentität als Default festlegen (Befehl 48, F7.4): zieht samt Verlauf
 *  zum Default um; die leere Kundenakte entfällt. Nur mit Bestätigung. */
function MakeDefault({ customer, identity }: { customer: CustomerSummary; identity: ChannelIdentity }) {
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  if (identity.platform !== "telegram" && identity.platform !== "instagram") return null;
  const assign = () =>
    void cmd.run(
      { case: "defaultSenderAssign", value: { customerId: customer.customerId, identityId: identity.identityId } },
      { done: "Absender ist jetzt Default." },
    );
  return (
    <div className="g-actions">
      {confirm ? (
        <>
          <button type="button" className="g-button g-primary" disabled={cmd.pending} onClick={assign}>
            Default bestätigen
          </button>
          <button type="button" className="g-button" onClick={() => setConfirm(false)}>
            Abbrechen
          </button>
        </>
      ) : (
        <button type="button" className="g-button" onClick={() => setConfirm(true)}>
          Als Default festlegen
        </button>
      )}
      {cmd.notice ? <small role="alert">{cmd.notice}</small> : null}
    </div>
  );
}
