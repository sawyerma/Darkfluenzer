import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import {
  PLATFORMS,
  PLATFORM_LABEL,
  closeRegister,
  customerName,
  handleLabel,
  markRead,
  markReadTarget,
  openRegister,
  platformTag,
  replyTarget,
  shortTime,
  useConversation,
  useCustomers,
  useRegisters,
  type Platform,
} from "../core/channels";
import { useCommand } from "../core/commands";
import type {
  ChannelIdentity,
  ChannelStatus,
  ConversationItem,
  CustomerSummary,
  DefaultContact,
  MessageAttachment,
} from "../core/generated/darkfluenzer/v1/channel_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { mediaUrl } from "../core/media";
import { useStateTopic } from "../core/state";
import { Candidates } from "./ComfyUI";

// Nachrichten (FRONT F4, F7.2–F7.4): links Kundenliste mit Kanalstatus, Mitte Register,
// Unterregister und Verlauf, rechts die Kundensteuerung. „Gesamter Verlauf“ ist nur lesbar;
// geantwortet wird ausschließlich im gewählten, verknüpften Kanal-Unterregister.

type Tone = "ok" | "warn" | "bad" | "neutral";
type View = "all" | Platform;

const CHANNEL_STATE: Record<string, [string, Tone]> = {
  OFF: ["NICHT EINGERICHTET", "neutral"],
  CONNECTING: ["VERBINDET", "warn"],
  READY: ["ANGEMELDET", "ok"],
  ERROR: ["FEHLER", "bad"],
};
// Kontoanmeldung (Telegram über TDLib, FRONT F4 V1.12 Punkt 1): Schritt -> Anzeige, Feld
const LOGIN_STEP: Record<string, [string, string, string]> = {
  phone: ["NICHT ANGEMELDET", "Telefonnummer", "tel"],
  code: ["CODE ERWARTET", "Code aus Telegram", "text"],
  password: ["PASSWORT ERWARTET", "Zwei-Faktor-Passwort", "password"],
};
const ITEM_STATUS: Record<string, string> = {
  queued: "wartet",
  sending: "wird gesendet",
  sent: "gesendet",
  failed: "fehlgeschlagen",
  unknown: "Ergebnis unbekannt",
};
const ATTACHMENT_KIND: Record<string, string> = {
  photo: "Foto",
  video: "Video",
  voice: "Sprachnachricht",
  audio: "Audio",
  document: "Dokument",
  sticker: "Sticker",
  share: "Geteilter Beitrag",
  reel: "Reel",
  post: "Beitrag",
  other: "Anhang",
};
const ATTACHMENT_STATUS: Record<string, string> = {
  saved: "gesichert",
  pending: "wird gesichert",
  too_large: "zu groß",
  not_importable: "nicht importierbar",
  failed: "fehlgeschlagen",
};
const ATTACHMENT_TYPE: Record<string, string> = { photo: "image", video: "video", reel: "video", voice: "audio", audio: "audio" };
const APPROVAL: readonly [string, string][] = [
  ["direct", "Direkt zurücksenden"],
  ["cockpit", "Nach Auswahl im Cockpit"],
  ["cockpit_only", "Nur Cockpit"],
];
const READ_ONLY = "Gesamter Verlauf · nur lesen. Antworten ausschließlich im gewählten Kanal.";
const AI_MISSING = "Text-KI nicht angeschlossen";
const STICK_PX = 48; // so nah am Ende folgt der Verlauf neuen Nachrichten

// Entwürfe je Kunde und Kanal; ein Unterregisterwechsel nimmt keinen Text in einen anderen Kanal mit.
const drafts = new Map<string, string>();

function useDocumentVisible(): boolean {
  return useSyncExternalStore(
    (fn) => {
      document.addEventListener("visibilitychange", fn);
      return () => document.removeEventListener("visibilitychange", fn);
    },
    () => document.visibilityState === "visible",
  );
}

function megabytes(size: bigint): string {
  return `${(Number(size) / 1e6).toFixed(1)} MB`;
}

/** Warum ein Kanal gerade nicht sendet: nicht eingerichtet (mit dem, was fehlt) oder nicht verbunden. */
function channelNote(ch: ChannelStatus | undefined, platform: string): string {
  const label = PLATFORM_LABEL[platform] ?? platform;
  if (!ch || ch.state === "OFF") return [`${label} nicht eingerichtet`, ch?.missing].filter(Boolean).join(" · ");
  if (ch.state === "READY") return "";
  return [`${label} nicht verbunden`, ch.error || ch.missing].filter(Boolean).join(" · ");
}

/** Anmeldung, Automatik und Abmelden eines Kanalkontos (Befehle 39/40). Eingaben werden nach
 *  jedem Schritt verworfen und nie angezeigt. */
function AccountControls({ ch }: { ch: ChannelStatus }) {
  const cmd = useCommand();
  const [value, setValue] = useState("");
  const [confirmLogout, setConfirmLogout] = useState(false);
  const step = LOGIN_STEP[ch.loginState];

  async function submit(e: FormEvent) {
    e.preventDefault();
    const entered = value.trim();
    setValue(""); // nie stehen lassen
    if (!entered) return;
    await cmd.run({ case: "channelAccountLogin", value: { platform: ch.platform, step: ch.loginState, value: entered } });
  }

  function update(action: string) {
    setConfirmLogout(false);
    void cmd.run({ case: "channelAccountUpdate", value: { platform: ch.platform, action } });
  }

  return (
    <>
      {ch.state === "LOGIN" && step ? (
        <form className="g-actions" onSubmit={submit}>
          <input
            className="g-input"
            type={step[2]}
            autoComplete="off"
            aria-label={step[1]}
            placeholder={ch.loginState === "password" && ch.loginHint ? `${step[1]} (Hinweis: ${ch.loginHint})` : step[1]}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button type="submit" className="g-button g-primary" disabled={cmd.pending || !value.trim()}>
            {ch.loginState === "phone" ? "Anmelden" : "Weiter"}
          </button>
        </form>
      ) : null}
      {ch.state === "READY" ? (
        <div className="g-actions">
          <button
            type="button"
            className="g-button"
            disabled={cmd.pending}
            onClick={() => update(ch.automation ? "disable_automation" : "enable_automation")}
          >
            {ch.automation ? "Automatik sperren" : "Automatik freigeben"}
          </button>
          {confirmLogout ? (
            <>
              <button type="button" className="g-button g-danger" disabled={cmd.pending} onClick={() => update("logout")}>
                Wirklich abmelden
              </button>
              <button type="button" className="g-button" onClick={() => setConfirmLogout(false)}>
                Abbrechen
              </button>
            </>
          ) : (
            <button type="button" className="g-button" onClick={() => setConfirmLogout(true)}>
              Abmelden
            </button>
          )}
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

/** Kanalstatus (STATE channels) kompakt in der linken Spalte. */
function ChannelLines({ channels, stale }: { channels: readonly ChannelStatus[] | undefined; stale: boolean }) {
  if (!channels) return <small>Kanalstatus: keine Daten</small>;
  return (
    <div>
      {channels.map((ch) => {
        const step = ch.state === "LOGIN" ? LOGIN_STEP[ch.loginState] : undefined;
        const [label, tone] = step
          ? [step[0], "warn" as Tone]
          : ch.state === "READY" && ch.testMode
              ? ["TESTBETRIEB", "warn" as Tone]
              : (CHANNEL_STATE[ch.state] ?? [ch.state || "UNBEKANNT", "neutral" as Tone]);
        const detail = ch.state === "READY" || ch.state === "LOGIN" ? "" : ch.error || ch.missing;
        const flood = Number(ch.floodUntilMs) > Date.now() ? `Telegram bremst bis ${shortTime(ch.floodUntilMs)}` : "";
        return (
          <div key={ch.platform} className="g-stack">
            <span className="g-between">
              <span className="g-ellipsis">
                <span className="g-ptag" data-platform={ch.platform}>
                  {PLATFORM_LABEL[ch.platform] ?? ch.platform}
                </span>{" "}
                {ch.account}
              </span>
              <span className="g-badge" data-tone={stale ? "stale" : tone}>
                {label}
              </span>
            </span>
            {detail ? ch.state === "ERROR" ? <span className="g-error">{detail}</span> : <small>{detail}</small> : null}
            {ch.testMode && ch.state !== "OFF" ? <small>TESTBETRIEB · nur freigegebene Test-Chats</small> : null}
            {flood ? <small className="g-error">{flood}</small> : null}
            {ch.state === "READY" && ch.automation ? <small>Automatik freigegeben</small> : null}
            <AccountControls ch={ch} />
          </div>
        );
      })}
    </div>
  );
}

function CustomerRow({ c, active }: { c: CustomerSummary; active: boolean }) {
  const last = c.lastText ? `${PLATFORM_LABEL[c.lastPlatform] ?? c.lastPlatform}: ${c.lastText}` : "Noch keine Nachricht";
  const desc =
    c.kind === "internal" ? (c.lastText ? last : "Interner Kontakt") : [c.displayName ? c.customerNo : "", last].filter(Boolean).join(" · ");
  const single = c.kind !== "internal" && c.platforms.length === 1 ? c.platforms[0] : undefined;
  const tag = platformTag(c);
  return (
    <button
      type="button"
      role="listitem"
      className="g-contact"
      aria-current={active ? "true" : undefined}
      onClick={() => openRegister(c.customerId)}
    >
      <span className="g-avatar" aria-hidden="true">
        {(c.displayName || c.customerNo.replace(/^DF-C-0*/, "")).charAt(0).toUpperCase()}
      </span>
      <span className="g-contact-main">
        <strong className="g-ellipsis">{customerName(c)}</strong>
        <small className="g-ellipsis">{desc}</small>
      </span>
      <span className="g-contact-side">
        {tag ? (
          <span className="g-ptag" data-platform={single}>
            {tag}
          </span>
        ) : null}
        {c.lastMs ? <small>{shortTime(c.lastMs)}</small> : null}
        {c.unread ? (
          <span className="g-unread" title={`${c.unread} ungelesen`}>
            {c.unread}
          </span>
        ) : null}
      </span>
    </button>
  );
}

/** Linke Spalte (F7.2): Kunden + Anzahl, Kanalstatus, Suche, Kundenzeilen (Default zuerst). */
function CustomerList({
  list,
  activeId,
  note,
  live,
}: {
  list: readonly CustomerSummary[];
  activeId: bigint | undefined;
  note: string;
  live: boolean;
}) {
  const [query, setQuery] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const channels = useStateTopic(Topic.CHANNELS);
  const q = query.trim().toLowerCase();
  const shown = list.filter(
    (c) =>
      (!unreadOnly || c.unread > 0) &&
      (!q || [c.displayName, c.customerNo, ...c.handles].some((v) => v.toLowerCase().includes(q))),
  );
  const count = list.filter((c) => c.kind === "customer").length;
  return (
    <div className="g-clist">
      <div className="g-line g-head">
        <h2>Kunden</h2>
        <span className="g-value">{count === 1 ? "1 Akte" : `${count} Akten`}</span>
      </div>
      <ChannelLines channels={channels?.value.channels} stale={!live || (channels?.staleSince ?? null) !== null} />
      <input
        className="g-input"
        type="search"
        placeholder="Name, Nummer oder Plattform-ID …"
        aria-label="Kunde suchen"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="g-subtabs" role="tablist" aria-label="Filter">
        {([false, true] as const).map((only) => (
          <button
            key={String(only)}
            type="button"
            role="tab"
            aria-selected={unreadOnly === only}
            onClick={() => setUnreadOnly(only)}
          >
            {only ? "Ungelesen" : "Alle"}
          </button>
        ))}
      </div>
      <div role="list" aria-label="Kundenakten">
        {shown.map((c) => (
          <CustomerRow key={String(c.customerId)} c={c} active={c.customerId === activeId} />
        ))}
      </div>
      {note ? (
        <p className="g-note">{note}</p>
      ) : (q || unreadOnly) && shown.length === 0 ? (
        <p className="g-note">{q ? "Keine Treffer." : "Keine ungelesenen Nachrichten."}</p>
      ) : count === 0 ? (
        <p className="g-note">Noch keine Kunden.</p>
      ) : null}
    </div>
  );
}

/** Geöffnete Kundenregister (F7.3): mehrere offen, × schließt nur das Register; Default bleibt. */
function Registers({ tabs, activeId }: { tabs: readonly CustomerSummary[]; activeId: bigint }) {
  return (
    <div className="g-registers" role="tablist" aria-label="Geöffnete Kundenakten">
      {tabs.map((c) => {
        const active = c.customerId === activeId;
        return (
          <div key={String(c.customerId)} className="g-register" data-active={active || undefined}>
            <button type="button" role="tab" aria-selected={active} title={c.customerNo} onClick={() => openRegister(c.customerId)}>
              {customerName(c)}
              {c.unread ? <span className="g-unread">{c.unread}</span> : null}
            </button>
            {c.kind === "internal" ? null : (
              <button
                type="button"
                className="g-register-x"
                aria-label={`Register ${customerName(c)} schließen`}
                title="Register schließen"
                onClick={() => closeRegister(c.customerId)}
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Anhang: gesicherte Bilder/Videos/Audio über die geschützte Medien-URL, sonst Art und Zustand. */
function Attachment({ a }: { a: MessageAttachment }) {
  const kind = ATTACHMENT_KIND[a.kind] ?? a.kind;
  const url = a.path && a.status === "saved" ? mediaUrl(a.path) : "";
  const type = a.mime.split("/")[0] || ATTACHMENT_TYPE[a.kind] || "";
  if (url && type === "image") {
    return (
      <a className="g-attach" href={url} target="_blank" rel="noreferrer">
        <img src={url} alt={kind} loading="lazy" />
      </a>
    );
  }
  if (url && (type === "video" || type === "audio")) {
    return (
      <span className="g-attach">
        {type === "video" ? <video src={url} controls preload="metadata" /> : <audio src={url} controls preload="metadata" />}
      </span>
    );
  }
  const text = [kind, a.size ? megabytes(a.size) : "", ATTACHMENT_STATUS[a.status] ?? a.status, a.note].filter(Boolean).join(" · ");
  return url ? (
    <a className="g-attach" href={url} target="_blank" rel="noreferrer">
      {text}
    </a>
  ) : (
    <small className="g-attach">{text}</small>
  );
}

const ORDER_STATUS: Record<string, string> = {
  producing: "In Produktion",
  review: "Zur Prüfung",
  approved: "Freigegeben",
  delivered: "Ausgeliefert",
  cancelled: "Abgebrochen",
};

/** INTERNER AUFTRAG (F4/F7.4): Befehl, Wunsch, Stufe mit Kandidaten (Auswahl, Wiederholen) und
 *  Fehlern; solange der Auftrag läuft, live aus dem Auftragszustand. Wartet der erkannte Auftrag
 *  auf den Betreiber (Automatische Produktionsaufträge aus), startet ihn genau ein Knopf. */
function OrderCard({ item }: { item: ConversationItem }) {
  const cmd = useCommand();
  const active = useStateTopic(Topic.ORDERS_ACTIVE)?.value.orders ?? [];
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const [head, ...detail] = item.text.split("\n");
  const order = item.order && (active.find((o) => o.orderNo === item.order?.orderNo) ?? item.order);
  return (
    <div className="g-event">
      <strong>{head}</strong>
      {detail.length ? <p>{detail.join(" ")}</p> : null}
      {order ? (
        <>
          <small>{ORDER_STATUS[order.status] ?? order.status}</small>
          <Candidates orders={[order]} titles={Object.fromEntries(workflows.map((w) => [w.key, w.title]))} heading={false} />
        </>
      ) : null}
      {item.awaitingStart ? (
        <div className="g-actions">
          <button
            type="button"
            className="g-button g-primary"
            disabled={cmd.pending}
            onClick={() => cmd.run({ case: "startClonerOrder", value: { itemId: item.itemId } })}
          >
            Auftrag starten
          </button>
        </div>
      ) : null}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
      <small>{shortTime(item.atMs)}</small>
    </div>
  );
}

/** Nachricht als Blase in Kanalfarbe mit Kanalname (eingehend links, ausgehend rechts) oder
 *  neutrale Systemkarte. */
function Entry({ item }: { item: ConversationItem }) {
  const attachments = item.attachments.map((a, n) => <Attachment key={n} a={a} />);
  if (item.order?.orderNo || item.awaitingStart) return <OrderCard item={item} />;
  if (item.platform === "system" || item.direction === "system") {
    return (
      <div className="g-event">
        <strong>{item.sender || "Systemereignis"}</strong>
        {item.text ? <p>{item.text}</p> : null}
        {attachments}
        <small>{shortTime(item.atMs)}</small>
        {item.error ? <p className="g-error">{item.error}</p> : null}
      </div>
    );
  }
  const out = item.direction === "out";
  const meta = [
    PLATFORM_LABEL[item.platform] ?? item.platform,
    item.sender,
    shortTime(item.atMs),
    out ? (ITEM_STATUS[item.status] ?? item.status) : "",
  ];
  return (
    <div className="g-bubble" data-platform={item.platform} data-dir={out ? "out" : "in"}>
      {item.text ? <p>{item.text}</p> : null}
      {attachments}
      <small>{meta.filter(Boolean).join(" · ")}</small>
      {item.error ? <p className="g-error">{item.error}</p> : null}
    </div>
  );
}

type Conv = ReturnType<typeof useConversation>;

/** Chronologie (F7.3): ältere Seiten nur auf Wunsch; folgt neuen Nachrichten, solange man unten ist. */
function Stream({ conv, items, view, live }: { conv: Conv; items: readonly ConversationItem[]; view: View; live: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const shownView = useRef(view);
  const newest = items.at(-1)?.itemId ?? 0n;
  useLayoutEffect(() => {
    if (shownView.current !== view) {
      shownView.current = view;
      stick.current = true;
    }
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [newest, view]);
  return (
    <div
      className="g-stream"
      ref={box}
      role="log"
      aria-label="Verlauf"
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
      }}
    >
      {conv.more ? (
        <div className="g-actions">
          <button type="button" className="g-button" disabled={conv.olderLoading || !live} onClick={conv.loadOlder}>
            Ältere laden
          </button>
        </div>
      ) : null}
      {items.map((i) => (
        <Entry key={String(i.itemId)} item={i} />
      ))}
      {items.length === 0 ? (
        <p className="g-note">
          {!conv.loaded ? (live ? "Lädt …" : "Keine Verbindung") : view === "all" ? "Noch keine Nachrichten." : "Keine Nachrichten in diesem Kanal."}
        </p>
      ) : null}
      {conv.error ? (
        <p className="g-note" role="alert">
          {conv.error}
        </p>
      ) : null}
    </div>
  );
}

/** Kanalgebundene Antwort (F4-Korrektur): nur an die eine verknüpfte Konversation dieses Kanals,
 *  auf der gesehenen Gesprächsrevision. KI-Antwort erst mit angeschlossener Text-KI. */
function Composer({
  customer,
  platform,
  identities,
  channel,
  loaded,
  live,
}: {
  customer: CustomerSummary;
  platform: Platform;
  identities: readonly ChannelIdentity[];
  channel: ChannelStatus | undefined;
  loaded: boolean;
  live: boolean;
}) {
  const key = `${customer.customerId}:${platform}`;
  const [text, setText] = useState(() => drafts.get(key) ?? "");
  const cmd = useCommand();
  const label = PLATFORM_LABEL[platform] ?? platform;
  const target = loaded ? replyTarget(identities, platform) : "Lädt …";
  const blocked = typeof target === "string" ? target : !live ? "Keine Verbindung" : channelNote(channel, platform);
  const handle = typeof target === "string" ? "" : handleLabel(target.handle) || target.platformUserId;

  function edit(value: string) {
    setText(value);
    if (value) drafts.set(key, value);
    else drafts.delete(key);
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (typeof target === "string" || blocked || !body) return;
    const done = await cmd.run({
      case: "sendReply",
      value: {
        customerId: customer.customerId,
        identityId: target.identityId,
        conversationId: target.conversationId,
        platform,
        revision: target.revision,
        text: body,
      },
    });
    if (done) {
      drafts.delete(key);
      setText("");
    }
  }

  return (
    <form className="g-compose" data-platform={platform} onSubmit={(e) => void send(e)}>
      <textarea
        className="g-input"
        aria-label={`Antwort über ${label}`}
        placeholder={`Nachricht über ${label} …`}
        value={text}
        disabled={typeof target === "string" || cmd.pending}
        onChange={(e) => edit(e.target.value)}
      />
      <div className="g-between">
        <small>{blocked || [label, handle].filter(Boolean).join(" · ")}</small>
        <span className="g-value">
          <button type="button" className="g-button g-ai" disabled title={AI_MISSING}>
            KI antworten
          </button>
          <button type="submit" className="g-button g-send" disabled={Boolean(blocked) || !text.trim() || cmd.pending}>
            Antwort senden
          </button>
        </span>
      </div>
      <small>KI antworten: {AI_MISSING}</small>
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </form>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Rechte Spalte für Kunden: nur Blöcke mit echten Daten (Identität); KI/Auftrag folgen mit C5. */
function CustomerPanel({ customer, identities }: { customer: CustomerSummary; identities: readonly ChannelIdentity[] }) {
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
          </div>
        ))}
      </div>
    </>
  );
}

type Run = ReturnType<typeof useCommand>["run"];

/** Operator-Felder des Default-Kontakts (F7.4, V0 §8.1); CAS über die gelesene Revision. */
function DefaultForm({
  contact,
  run,
  pending,
  channels,
  live,
}: {
  contact: DefaultContact;
  run: Run;
  pending: boolean;
  channels: readonly ChannelStatus[];
  live: boolean;
}) {
  const [telegram, setTelegram] = useState(contact.telegramSenderId);
  const [instagram, setInstagram] = useState(contact.instagramSenderId);
  const [processCommands, setProcessCommands] = useState(contact.processCommands);
  const [autoOrders, setAutoOrders] = useState(contact.autoOrders);
  const [approval, setApproval] = useState(contact.approvalMode || "cockpit");
  const [influencer, setInfluencer] = useState(contact.influencer);
  const [workflow, setWorkflow] = useState(contact.mediaWorkflow);
  const [video, setVideo] = useState(contact.videoWorkflow);
  const registry = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const characters = useStateTopic(Topic.CHARACTERS)?.value.characters ?? [];
  const usable = registry.filter((w) => w.enabled && w.modelsReady && w.instance !== "ai" && !w.training);
  const media = usable.filter((w) => w.kind === "image");
  // animate: Foto -> Video, also ein Video-Workflow mit Eingangsbild
  const videos = usable.filter((w) => w.kind === "video" && w.params.some((x) => x.upload && x.name === "image"));
  const changed =
    telegram.trim() !== contact.telegramSenderId ||
    instagram.trim() !== contact.instagramSenderId ||
    processCommands !== contact.processCommands ||
    autoOrders !== contact.autoOrders ||
    approval !== contact.approvalMode ||
    influencer.trim() !== contact.influencer ||
    workflow !== contact.mediaWorkflow ||
    video !== contact.videoWorkflow;

  function submit(e: FormEvent) {
    e.preventDefault();
    void run(
      {
        case: "defaultContactUpdate",
        value: {
          revision: contact.revision,
          telegramSenderId: telegram.trim(),
          instagramSenderId: instagram.trim(),
          processCommands,
          autoOrders,
          approvalMode: approval,
          influencer: influencer.trim(),
          mediaWorkflow: workflow,
          videoWorkflow: video,
        },
      },
      { done: "Einstellungen übernommen." },
    );
  }

  // Absender-IDs gehören zum Konto der Influencerin: nur bei verbundenem Kanal (Konto bekannt) änderbar
  function sender(platform: string, value: string, set: (v: string) => void) {
    const ch = channels.find((c) => c.platform === platform);
    const id = `df-${platform}`;
    return (
      <div className="g-field g-wide">
        <label htmlFor={id}>{PLATFORM_LABEL[platform]}-Absender-ID</label>
        <input
          id={id}
          className="g-mono"
          value={value}
          placeholder={`${PLATFORM_LABEL[platform]}-ID zuordnen`}
          disabled={!ch?.account}
          onChange={(e) => set(e.target.value)}
        />
        {ch?.account ? null : <small>{channelNote(ch, platform) || `${PLATFORM_LABEL[platform]}-Konto unbekannt`}</small>}
      </div>
    );
  }

  function choice(id: string, label: string, value: string, set: (v: string) => void, options: typeof usable) {
    return (
      <div className="g-field">
        <label htmlFor={id}>{label}</label>
        <select id={id} value={value} onChange={(e) => set(e.target.value)}>
          <option value="">Nicht festgelegt</option>
          {options.map((w) => (
            <option key={w.key} value={w.key}>
              {w.title}
            </option>
          ))}
          {value && !options.some((w) => w.key === value) ? <option value={value}>{value} (nicht verfügbar)</option> : null}
        </select>
      </div>
    );
  }

  return (
    <form className="g-form" onSubmit={submit}>
      <div className="g-control-part g-wide">
        <h3>Identität &amp; Dialog</h3>
        <dl className="g-params">
          <Row label="Kontakt">Default</Row>
          <Row label="Aufgabe">Eigener Absender</Row>
        </dl>
        {sender("telegram", telegram, setTelegram)}
        {sender("instagram", instagram, setInstagram)}
        <label className="g-switch">
          <input type="checkbox" checked={processCommands} onChange={(e) => setProcessCommands(e.target.checked)} />
          Interne Befehle verarbeiten
        </label>
      </div>
      <div className="g-control-part g-wide">
        <h3>KI &amp; Medien</h3>
        <div className="g-field">
          <label htmlFor="df-influencer">Influencerin</label>
          <select id="df-influencer" value={influencer} onChange={(e) => setInfluencer(e.target.value)}>
            <option value="">Nicht festgelegt</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
            {influencer && !characters.some((c) => c.id === influencer) ? <option value={influencer}>{influencer} (unbekannt)</option> : null}
          </select>
        </div>
        {choice("df-workflow", "Medien-Workflow", workflow, setWorkflow, media)}
        {choice("df-video", "Video-Workflow (animate)", video, setVideo, videos)}
        <div className="g-field">
          <label htmlFor="df-approval">Freigabemodus</label>
          <select id="df-approval" value={approval} onChange={(e) => setApproval(e.target.value)}>
            {APPROVAL.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <label className="g-switch">
          <input type="checkbox" checked={autoOrders} onChange={(e) => setAutoOrders(e.target.checked)} />
          Automatische Produktionsaufträge
        </label>
      </div>
      <div className="g-control-part g-wide">
        <h3>Einstellungen</h3>
      </div>
      <button type="submit" className="g-button g-primary g-block g-wide" disabled={!live || pending || !changed}>
        Einstellungen übernehmen
      </button>
    </form>
  );
}

function DefaultPanel({
  contact,
  loaded,
  channels,
  live,
}: {
  contact: DefaultContact | undefined;
  loaded: boolean;
  channels: readonly ChannelStatus[];
  live: boolean;
}) {
  const cmd = useCommand();
  return (
    <>
      <div className="g-line g-head">
        <h2>Default · Steuerung</h2>
        <span className="g-badge">INTERN</span>
      </div>
      {contact ? (
        // neue Revision (eigene oder fremde Änderung): Formular zeigt den gespeicherten Stand
        <DefaultForm key={String(contact.revision)} contact={contact} run={cmd.run} pending={cmd.pending} channels={channels} live={live} />
      ) : (
        <p className="g-note">{loaded ? "Keine Default-Einstellungen vom Backend." : "Lädt …"}</p>
      )}
      {cmd.notice ? (
        <p className="g-note" role="alert">
          {cmd.notice}
        </p>
      ) : null}
    </>
  );
}

/** Mitte und rechte Spalte einer Kundenakte; ein Registerwechsel tauscht beide gemeinsam. */
function CustomerFile({ customer, registers, live }: { customer: CustomerSummary; registers: ReactNode; live: boolean }) {
  const conv = useConversation(customer.customerId);
  const channels = useStateTopic(Topic.CHANNELS)?.value.channels ?? [];
  const [chosen, setChosen] = useState<View>("all");
  const visible = useDocumentVisible();
  const linked = new Set([...customer.platforms, ...conv.identities.map((i) => i.platform)]);
  const view: View = chosen !== "all" && linked.has(chosen) ? chosen : "all";
  const platform = view === "all" ? null : view;
  const shown = platform ? conv.items.filter((i) => i.platform === platform) : conv.items;
  const internal = customer.kind === "internal";
  const handles = [...new Set(conv.identities.map((i) => handleLabel(i.handle)).filter(Boolean))];
  const sub = internal ? [customer.customerNo, "Interner Kontakt"] : [customer.customerNo, ...handles];

  useEffect(() => {
    // sichtbarer Verlauf: gelesen bis zum neuesten Eingang dieser Ansicht (einmal je neuem Eingang)
    if (live && visible && conv.loaded && !conv.stale) markRead(customer.customerId, markReadTarget(conv.items, platform));
  }, [live, visible, conv.loaded, conv.stale, conv.items, platform, customer.customerId]);

  return (
    <>
      <div className="g-chat">
        {registers}
        <div className="g-chathead g-between">
          <div className="g-contact-main">
            <h2 className="g-ellipsis">{customerName(customer)}</h2>
            <small className="g-ellipsis">{sub.filter(Boolean).join(" · ")}</small>
          </div>
          {conv.stale && conv.loaded ? (
            <span className="g-badge" data-tone="stale">
              VERALTET
            </span>
          ) : null}
        </div>
        <div className="g-channels" role="tablist" aria-label="Kanal">
          <button type="button" role="tab" aria-selected={view === "all"} onClick={() => setChosen("all")}>
            Gesamter Verlauf
          </button>
          {PLATFORMS.map((p) => (
            <button
              key={p}
              type="button"
              role="tab"
              data-platform={p}
              aria-selected={view === p}
              disabled={!linked.has(p)}
              title={linked.has(p) ? undefined : "Kanal nicht verknüpft"}
              onClick={() => setChosen(p)}
            >
              {PLATFORM_LABEL[p]}
            </button>
          ))}
        </div>
        <Stream conv={conv} items={shown} view={view} live={live} />
        {platform ? (
          <Composer
            key={`${customer.customerId}:${platform}`}
            customer={customer}
            platform={platform}
            identities={conv.identities}
            channel={channels.find((c) => c.platform === platform)}
            loaded={conv.loaded}
            live={live && !conv.stale}
          />
        ) : (
          <p className="g-note">{READ_ONLY}</p>
        )}
      </div>
      <aside className="g-control" aria-label="Kundensteuerung">
        {internal ? (
          <DefaultPanel contact={conv.defaultContact} loaded={conv.loaded} channels={channels} live={live && !conv.stale} />
        ) : (
          <CustomerPanel customer={customer} identities={conv.identities} />
        )}
      </aside>
    </>
  );
}

export function Messages() {
  const customers = useCustomers();
  const registers = useRegisters();
  const { list, live } = customers;
  const def = list.find((c) => c.kind === "internal");
  const byId = new Map(list.map((c) => [c.customerId, c] as const));
  const tabs = [
    ...(def ? [def] : []),
    ...registers.open.filter((id) => id !== def?.customerId).flatMap((id) => byId.get(id) ?? []),
  ];
  const current = tabs.find((c) => c.customerId === registers.active) ?? tabs[0];
  const note = customers.loaded ? "" : customers.error || (live ? "Lädt …" : "Keine Verbindung");

  return (
    <section className="g-panel">
      <h1>Nachrichten</h1>
      <div className="g-inbox">
        <CustomerList list={list} activeId={current?.customerId} note={note} live={live} />
        {current ? (
          <CustomerFile
            key={String(current.customerId)}
            customer={current}
            registers={<Registers tabs={tabs} activeId={current.customerId} />}
            live={live}
          />
        ) : (
          <>
            <div className="g-chat">
              <p className="g-note">{note || "Keine Kundenakte geöffnet."}</p>
            </div>
            <aside className="g-control" aria-label="Kundensteuerung">
              <h2>Kundenakte</h2>
            </aside>
          </>
        )}
      </div>
      {customers.loaded && customers.error ? (
        <p className="g-note" role="alert">
          {customers.error}
        </p>
      ) : null}
    </section>
  );
}
