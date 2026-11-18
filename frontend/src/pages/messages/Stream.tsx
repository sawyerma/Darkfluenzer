import { ATTACHMENT_KIND, ATTACHMENT_STATUS, ATTACHMENT_TYPE, DELIVERY_STATUS, ITEM_STATUS, METHOD_LABEL, ORDER_STATUS, STICK_PX, Tone, View, clonerHead } from "./common";
import type { ActiveOrder } from "../../core/generated/darkfluenzer/v1/order_pb";
import { Candidates } from "../comfyui/Candidates";
import type { ConversationItem, MessageAttachment } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { PLATFORM_LABEL, shortTime, useConversation } from "../../core/channels";
import { Row } from "./CustomerPanel";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { mediaUrl } from "../../core/media";
import { setProductionIntent } from "../../core/intent";
import { useCommand } from "../../core/commands";
import { useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useStateTopic } from "../../core/state";

export function useDocumentVisible(): boolean {
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

export const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

/** Kundenauftrag in der Karte ANGEBOT (V0 §8.4): Angebot mit eindeutigen Beträgen, Zahlung,
 *  Produktion im ComfyUI-Reiter, „Freigeben & senden“ hinter approval.py, Zustellungen. */
function CustomerOrder({ order }: { order: ActiveOrder }) {
  const cmd = useCommand();
  const [notExplicit, setNotExplicit] = useState(false);
  const offer = order.offer;
  const expired = offer && Number(offer.expiresMs) < Date.now() && ["offered", "accepted"].includes(order.status);
  const last = order.deliveries.at(-1);
  const standard = order.resultTier === "standard";
  return (
    <>
      {offer ? (
        <dl className="g-params">
          <Row label="Angebot">
            {offer.product}
            {offer.hd ? " + HD" : ""} · {EUR.format(offer.priceCents / 100)}
          </Row>
          <Row label="Gültig bis">{expired ? `abgelaufen (${shortTime(offer.expiresMs)})` : shortTime(offer.expiresMs)}</Row>
          {offer.amounts.map((a) => (
            <Row key={a.method} label={METHOD_LABEL[a.method] ?? a.method}>
              <span className="g-mono">
                {a.amount} {a.asset}
              </span>
              <small className="g-mono"> an {a.address}</small>
            </Row>
          ))}
        </dl>
      ) : null}
      {order.status === "paid" ? (
        <div className="g-actions">
          <button type="button" className="g-button g-primary" onClick={() => setProductionIntent(order.orderNo)}>
            In ComfyUI produzieren
          </button>
        </div>
      ) : null}
      {order.status === "review" && order.resultMediaId ? (
        <div className="g-stack">
          {order.resultPath ? (
            <a className="g-attach" href={mediaUrl(order.resultPath)} target="_blank" rel="noreferrer">
              <img src={mediaUrl(order.resultPath)} alt="Ergebnis zur Freigabe" loading="lazy" />
            </a>
          ) : null}
          <small>Inhaltsstufe: {order.resultTier || "unbekannt (gilt als explizit)"}</small>
          {standard ? (
            <>
              <label className="g-switch">
                <input type="checkbox" checked={notExplicit} onChange={(e) => setNotExplicit(e.target.checked)} />
                Ergebnis ist nicht explizit
              </label>
              <div className="g-actions">
                <button
                  type="button"
                  className="g-button g-primary"
                  disabled={!notExplicit || cmd.pending}
                  onClick={() =>
                    void cmd.run(
                      { case: "approveArtifact", value: { orderNo: order.orderNo, mediaId: order.resultMediaId, notExplicit } },
                      { done: "Freigegeben · Zustellung im Postausgang." },
                    )
                  }
                >
                  Freigeben &amp; senden
                </button>
              </div>
            </>
          ) : (
            <small className="g-error">An Kunden nur Inhaltsstufe standard (Regel 13).</small>
          )}
        </div>
      ) : null}
      {order.deliveries.map((d) => {
        const [label, tone] = DELIVERY_STATUS[d.status] ?? [d.status, "neutral" as Tone];
        return (
          <span key={String(d.deliveryId)} className="g-between">
            <small>
              Zustellung {shortTime(d.atMs)}
              {d.error ? ` · ${d.error}` : ""}
            </small>
            <span className="g-badge" data-tone={tone}>
              {label}
            </span>
          </span>
        );
      })}
      {last?.status === "unknown" ? <small>Versand ungeklärt – im Kanal prüfen; kein automatischer Neuversuch.</small> : null}
      {order.status === "approved" && last?.status === "failed" ? (
        <div className="g-actions">
          <button
            type="button"
            className="g-button"
            disabled={cmd.pending}
            onClick={() => void cmd.run({ case: "retryDelivery", value: { orderNo: order.orderNo } }, { done: "Erneut im Postausgang." })}
          >
            Erneut senden
          </button>
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

/** INTERNER AUFTRAG (F4/F7.4): Befehl, Wunsch, Stufe mit Kandidaten (Auswahl, Wiederholen) und
 *  Fehlern; solange der Auftrag läuft, live aus dem Auftragszustand. Wartet der erkannte Auftrag
 *  auf den Betreiber (Automatische Produktionsaufträge aus), startet ihn genau ein Knopf. */
function OrderCard({ item }: { item: ConversationItem }) {
  const cmd = useCommand();
  const active = useStateTopic(Topic.ORDERS_ACTIVE)?.value.orders ?? [];
  const workflows = useStateTopic(Topic.COMFY_WORKFLOWS)?.value.workflows ?? [];
  const [head = "", ...detail] = item.text.split("\n");
  const order = item.order && (active.find((o) => o.orderNo === item.order?.orderNo) ?? item.order);
  const state = clonerHead(head);
  return (
    <div className="g-event">
      {state ? (
        <span className="g-between">
          <strong>{state[0]}</strong>
          <span className="g-badge" data-tone={state[2]}>
            {state[1]}
          </span>
        </span>
      ) : (
        <strong>{head}</strong>
      )}
      {detail.length ? <p>{detail.join(" ")}</p> : null}
      {order ? (
        <>
          <small>
            {order.orderNo} · {ORDER_STATUS[order.status] ?? order.status}
          </small>
          {order.source === "customer" ? <CustomerOrder order={order} /> : null}
          {order.stages.length ? (
            <Candidates orders={[order]} titles={Object.fromEntries(workflows.map((w) => [w.key, w.title]))} heading={false} />
          ) : null}
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

/** Sendung mit unbekanntem Ergebnis (SPEC-009, Befehl 66): der Betreiber entscheidet; „Erneut
 *  senden“ erst nach einer zweiten Bestätigung, weil die erste Sendung angekommen sein kann. */
function UnknownActions({ item }: { item: ConversationItem }) {
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  const resolve = (action: string, done: string) =>
    void cmd.run({ case: "messageResolve", value: { messageId: item.itemId, action } }, { done });
  return (
    <div className="g-actions">
      {confirm ? (
        <>
          <small className="g-warn">Kann doppelt ankommen</small>
          <button type="button" className="g-button g-danger" disabled={cmd.pending} onClick={() => resolve("resend", "Erneut eingereiht.")}>
            Trotzdem erneut senden
          </button>
          <button type="button" className="g-button" onClick={() => setConfirm(false)}>
            Abbrechen
          </button>
        </>
      ) : (
        <>
          <button type="button" className="g-button" disabled={cmd.pending} onClick={() => resolve("mark_sent", "Als gesendet markiert.")}>
            Als gesendet markieren
          </button>
          <button type="button" className="g-button" disabled={cmd.pending} onClick={() => setConfirm(true)}>
            Erneut senden
          </button>
        </>
      )}
      {cmd.notice ? (
        <p className="g-note" role="status">
          {cmd.notice}
        </p>
      ) : null}
    </div>
  );
}

/** Nachricht als Blase in Kanalfarbe mit Kanalname (eingehend links, ausgehend rechts) oder
 *  neutrale Systemkarte. */
function Entry({ item }: { item: ConversationItem }) {
  const attachments = item.attachments.map((a, n) => <Attachment key={n} a={a} />);
  // Kloner-Karten mit Zustand (SP1 Schritt 5) auch ohne Auftrag: Abgelehnt, Fehlgeschlagen
  if (item.order?.orderNo || item.awaitingStart || item.text.startsWith("INTERNER AUFTRAG")) return <OrderCard item={item} />;
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
  // Bearbeitung und Löschung meldet die Plattform (SP2 Schritt 5); der Inhalt bleibt sichtbar
  const edited = Number(item.editedAtMs) > 0;
  const deleted = Number(item.deletedAtMs) > 0;
  const meta = [
    PLATFORM_LABEL[item.platform] ?? item.platform,
    item.sender,
    shortTime(item.atMs),
    out ? (ITEM_STATUS[item.status] ?? item.status) : "",
    edited ? `bearbeitet ${shortTime(item.editedAtMs)}` : "",
    deleted ? `gelöscht ${shortTime(item.deletedAtMs)}` : "",
  ];
  return (
    <div className="g-bubble" data-platform={item.platform} data-dir={out ? "out" : "in"} data-deleted={deleted || undefined}>
      {item.text ? <p>{item.text}</p> : null}
      {edited && item.originalText ? (
        <details className="g-orig">
          <summary>Erster Text</summary>
          <p>{item.originalText}</p>
        </details>
      ) : null}
      {attachments}
      <small>{meta.filter(Boolean).join(" · ")}</small>
      {item.error ? <p className="g-error">{item.error}</p> : null}
      {out && item.status === "unknown" ? <UnknownActions item={item} /> : null}
    </div>
  );
}

type Conv = ReturnType<typeof useConversation>;

/** Chronologie (F7.3): ältere Seiten nur auf Wunsch; folgt neuen Nachrichten, solange man unten ist. */
export function Stream({ conv, items, view, live }: { conv: Conv; items: readonly ConversationItem[]; view: View; live: boolean }) {
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
