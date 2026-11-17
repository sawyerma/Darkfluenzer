import { useEffect, useRef, useState, type ReactNode } from "react";
import { openRegister, shortTime } from "../core/channels";
import { useCommand } from "../core/commands";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import type { OpenOffer, Payment, Voucher, WalletAccount, WalletSource } from "../core/generated/darkfluenzer/v1/wallet_pb";
import { useStateTopic } from "../core/state";
import { usePayments, type PaymentFilter, type PaymentsStatus } from "../core/wallet";
import { clock } from "./comfyui/common";

// Wallet (FRONT F7.8, V0 §8.5): Claras Konten werden nur beobachtet – Kontokarten mit Guthaben,
// Schublade mit Adresse und QR, Zahlungseingänge mit Filter und Seiten (nicht zugeordnete einem
// offenen Angebot zuordnen, Befehl 41), Amazon-Gutscheine zu prüfen (Befehl 42), Monatsliste als
// Datei, Datenquellen. Kein Seed, kein Schlüssel, kein Senden.

type Tone = "ok" | "warn" | "bad" | "neutral";

const ACCOUNT_STATE: Record<string, [string, Tone]> = {
  OK: ["AKTUELL", "ok"],
  STALE: ["VERALTET", "warn"],
  ERROR: ["FEHLER", "bad"],
  MISSING: ["NICHT EINGERICHTET", "neutral"],
};
// Wege ohne Backend-Anschluss: ehrlich als nicht eingerichtet, ohne Aktion (PayPal braucht den Tunnel).
const NOT_CONNECTED: readonly [string, string, string][] = [["paypal", "PayPal", "Bestätigte Eingänge im Monat · nicht angeschlossen"]];
const VOUCHER_STATUS: Record<string, [string, Tone]> = {
  pending: ["zu prüfen", "warn"],
  redeemed: ["eingelöst", "ok"],
  rejected: ["abgelehnt", "neutral"],
};
const NETWORK: Record<string, string> = { bitcoin: "Bitcoin", bsc: "BNB Smart Chain (BSC)", paypal: "PayPal", amazon: "Amazon" };
const METHOD: Record<string, string> = {
  btc: "Bitcoin",
  usdt: "USDT · BSC",
  usdc: "USDC · BSC",
  paypal: "PayPal",
  amazon: "Amazon-Gutschein",
};
const STATUS: Record<string, [string, Tone]> = {
  confirmed: ["bestätigt", "ok"],
  assigned: ["zugeordnet", "ok"],
  unassigned: ["nicht zugeordnet", "warn"],
  expired: ["abgelaufen", "neutral"],
};
const FILTERS: readonly [PaymentFilter, string][] = [
  ["all", "Alle"],
  ["open", "Offen"],
  ["confirmed", "Bestätigt"],
  ["unassigned", "Nicht zugeordnet"],
];
const LOAD_NOTE: Record<Exclude<PaymentsStatus, "ready">, string> = { loading: "Lädt …", offline: "Keine Verbindung" };
const EMPTY: Record<PaymentFilter, string> = {
  all: "Noch keine Zahlungseingänge.",
  open: "Keine offenen Eingänge.",
  confirmed: "Keine bestätigten Eingänge.",
  unassigned: "Keine nicht zugeordneten Eingänge.",
};

const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const RATE = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 6 });

/** Dezimaltext des Backends exakt in deutscher Schreibweise (auch Exponentform wie „1E+1“). */
function decimal(text: string): string {
  const m = /^(-?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text.trim());
  if (!text || !m) return text || "–";
  const [, sign = "", int = "", frac = "", exp = "0"] = m;
  let digits = int + frac;
  let point = int.length + Number(exp);
  if (point <= 0) {
    digits = "0".repeat(1 - point) + digits;
    point = 1;
  }
  digits = digits.padEnd(point, "0");
  const whole = digits.slice(0, point).replace(/^0+(?=\d)/, "") || "0";
  const rest = digits.slice(point).replace(/0+$/, "");
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".")}${rest ? `,${rest}` : ""}`;
}

function dateTime(ms: bigint): string {
  if (!ms) return "–";
  return new Date(Number(ms)).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const euro = (value: number, rateMs: bigint) => (rateMs ? EUR.format(value) : "kein Kurs");
const shortTx = (txid: string) => (txid.length > 18 ? `${txid.slice(0, 10)}…${txid.slice(-6)}` : txid || "–");

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Was Karte und Schublade gemeinsam zeigen. Ein Wert ohne frische Prüfung (STALE, ERROR oder
 *  getrennte Verbindung) bleibt sichtbar, ist aber gedimmt und als veraltet beschriftet. */
function view(a: WalletAccount, stale: boolean) {
  const checked = a.state !== "MISSING" && a.checkedMs > 0n;
  const old = checked && (stale || a.state !== "OK");
  const [label, tone]: [string, Tone] =
    a.state === "STALE" && !checked
      ? ["PRÜFUNG AUSSTEHEND", "warn"]
      : stale && a.state === "OK"
        ? ["VERALTET", "warn"]
        : (ACCOUNT_STATE[a.state] ?? [a.state || "UNBEKANNT", "neutral"]);
  return {
    checked,
    old,
    value: checked && a.rateMs ? EUR.format(a.eurTotal) : "–",
    badge: (
      <span className="g-badge" data-tone={stale ? "stale" : tone}>
        {label}
      </span>
    ),
    note: a.state === "MISSING" ? a.missing : a.state === "ERROR" ? a.error : "",
    checkedText: (time: (ms: bigint) => string) =>
      checked ? `${old ? "veraltet · " : ""}${a.checkedAt || "geprüft"} · ${time(a.checkedMs)}` : "noch nicht geprüft",
  };
}

/** Kontokarte wie in der DarkBot-Wallet: Titel mit Chevron, großer Wert, Zustand; Klick öffnet die Schublade. */
function AccountCard({ a, stale, onOpen }: { a: WalletAccount; stale: boolean; onOpen: () => void }) {
  const v = view(a, stale);
  return (
    <button type="button" className="g-card g-account" data-stale={v.old || undefined} onClick={onOpen}>
      <span className="g-account-head">
        {a.title}
        <span aria-hidden="true">›</span>
      </span>
      <strong className="g-account-value">{v.value}</strong>
      {v.checked
        ? a.balances.map((b) => (
            <small key={b.asset}>
              {decimal(b.amount)} {b.asset} · {euro(b.eur, a.rateMs)}
            </small>
          ))
        : null}
      {v.checked && a.balances.length === 0 ? <small>kein Guthaben</small> : null}
      {v.checked ? <small>Kurs {a.rateMs ? shortTime(a.rateMs) : "fehlt"}</small> : null}
      {a.state !== "MISSING" ? <small>{v.checkedText(shortTime)}</small> : null}
      <span className="g-account-badges">{v.badge}</span>
      {v.note ? a.state === "ERROR" ? <span className="g-error">{v.note}</span> : <small>{v.note}</small> : null}
    </button>
  );
}

/** Schublade eines Kontos: öffentliche Adresse mit Kopieren und QR, Netz, letzte Prüfung, Datenquelle. */
function AccountDetail({ a, stale, onClose }: { a: WalletAccount; stale: boolean; onClose: () => void }) {
  const [copied, setCopied] = useState("");
  const v = view(a, stale);

  async function copy() {
    try {
      await navigator.clipboard.writeText(a.address);
      setCopied("Kopiert");
    } catch {
      setCopied("Kopieren nicht möglich");
    }
  }

  return (
    <>
      <div className="g-line g-head">
        <h2 id="wallet-account">{a.title}</h2>
        <button type="button" className="g-button" onClick={onClose}>
          Schließen
        </button>
      </div>
      <strong className="g-account-value" data-stale={v.old || undefined}>
        {v.value}
      </strong>
      <dl className="g-params">
        {v.checked
          ? a.balances.map((b) => (
              <Row key={b.asset} label={b.asset}>
                {decimal(b.amount)} · {euro(b.eur, a.rateMs)}
              </Row>
            ))
          : null}
        <Row label="Zustand">
          {v.badge} {v.note}
        </Row>
        <Row label="Adresse">{a.address ? <span className="g-mono">{a.address}</span> : "–"}</Row>
        <Row label="Netz">{NETWORK[a.network] ?? a.network}</Row>
        <Row label="Geprüft">{v.checkedText(dateTime)}</Row>
        <Row label="Kurszeit">{dateTime(a.rateMs)}</Row>
        <Row label="Datenquelle">{a.source || "–"}</Row>
      </dl>
      {a.address ? (
        <>
          <div className="g-actions">
            <button type="button" className="g-button" onClick={() => void copy()}>
              Kopieren
            </button>
            {copied ? <small role="status">{copied}</small> : null}
          </div>
          <img className="g-qr" src={`/api/v1/wallet-qr/${encodeURIComponent(a.key)}`} alt={`QR-Code der Adresse ${a.title}`} />
        </>
      ) : null}
    </>
  );
}

/** Zustand der Datenquellen (STATE wallet) als ein Abzeichen im Kopf. */
function SourcesBadge({ sources, has, staleSince }: { sources: readonly WalletSource[]; has: boolean; staleSince: number | null }) {
  const failed = sources.filter((s) => s.error);
  const waiting = sources.filter((s) => !s.error && !s.okMs);
  const [label, tone]: [string, Tone] = !has
    ? ["KEINE DATEN", "neutral"]
    : sources.length === 0
      ? ["NICHT EINGERICHTET", "neutral"]
      : failed.length
        ? [`${failed.length} ${failed.length === 1 ? "QUELLE" : "QUELLEN"} GESTÖRT`, "bad"]
        : waiting.length
          ? ["ERSTE ABFRAGE LÄUFT", "warn"]
          : ["QUELLEN OK", "ok"];
  return (
    <span className="g-value">
      {staleSince !== null ? <small>veraltet seit {clock(staleSince)}</small> : null}
      <span className="g-badge" data-tone={staleSince !== null ? "stale" : tone} title={failed.map((s) => `${s.name}: ${s.error}`).join("\n") || undefined}>
        {label}
      </span>
    </span>
  );
}

function PaymentStatus({ p }: { p: Payment }) {
  const [label, tone]: [string, Tone] =
    p.status === "detected"
      ? [p.requiredConfirmations ? `erkannt ${p.confirmations}/${p.requiredConfirmations} Bestätigungen` : "erkannt", "warn"]
      : (STATUS[p.status] ?? [p.status || "unbekannt", "neutral"]);
  return (
    <span className="g-badge" data-tone={tone}>
      {label}
    </span>
  );
}

/** Nicht zugeordneten Eingang einem offenen Angebot zuordnen (Befehl 41, protokolliert). */
function Assign({ p, offers }: { p: Payment; offers: readonly OpenOffer[] }) {
  const cmd = useCommand();
  const [orderNo, setOrderNo] = useState("");
  if (p.status !== "unassigned") return null;
  if (offers.length === 0) return <small>kein offenes Angebot</small>;
  return (
    <span className="g-value">
      <select className="g-input" aria-label="Offenes Angebot" value={orderNo} onChange={(e) => setOrderNo(e.target.value)}>
        <option value="">Angebot wählen …</option>
        {offers.map((o) => (
          <option key={o.orderNo} value={o.orderNo}>
            {o.orderNo} · {o.displayName || o.customerNo} · {o.product} · {EUR.format(o.priceCents / 100)} · {o.amounts.join(", ")}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="g-button"
        disabled={!orderNo || cmd.pending}
        onClick={() => void cmd.run({ case: "paymentAssign", value: { paymentId: p.paymentId, orderNo } }, { done: "Zugeordnet." })}
      >
        Zuordnen
      </button>
      {cmd.notice ? <small role="alert">{cmd.notice}</small> : null}
    </span>
  );
}

function PaymentRow({ p, offers }: { p: Payment; offers: readonly OpenOffer[] }) {
  const who = [p.customerNo, p.orderNo].filter(Boolean).join(" · ") || "–";
  return (
    <tr>
      <td className="g-nowrap">{dateTime(p.atMs)}</td>
      <td className="g-nowrap">{METHOD[p.method] ?? p.method}</td>
      <td className="g-num">
        {decimal(p.amount)} {p.asset}
      </td>
      <td className="g-num" title={p.rate ? `Kurs ${RATE.format(p.rate)} € je ${p.asset} · ${dateTime(p.rateMs)}` : undefined}>
        {p.rateMs || p.eur ? EUR.format(p.eur) : "–"}
      </td>
      <td>
        {p.customerId ? (
          <button
            type="button"
            className="g-row"
            title="Kundenakte öffnen"
            onClick={() => {
              openRegister(p.customerId);
              window.location.hash = "#nachrichten";
            }}
          >
            {who}
          </button>
        ) : (
          who
        )}
      </td>
      <td className="g-mono" title={p.txid || undefined}>
        {shortTx(p.txid)}
      </td>
      <td>
        <PaymentStatus p={p} />
      </td>
      <td>
        <Assign p={p} offers={offers} />
      </td>
    </tr>
  );
}

/** Zahlungseingänge: Filter, Tabelle, „Ältere laden“; neue und geänderte Eingänge per Push. */
function Payments({ offers }: { offers: readonly OpenOffer[] }) {
  const [filter, setFilter] = useState<PaymentFilter>("all");
  const pay = usePayments(filter);
  const note = pay.status === "ready" ? EMPTY[filter] : pay.error ? "" : LOAD_NOTE[pay.status];
  return (
    <div className="g-section">
      <div className="g-between">
        <h2>Zahlungseingänge</h2>
        {pay.status === "ready" && !pay.live ? (
          <span className="g-badge" data-tone="stale">
            VERALTET
          </span>
        ) : null}
      </div>
      <div className="g-subtabs" role="tablist" aria-label="Zahlungsfilter">
        {FILTERS.map(([f, label]) => (
          <button key={f} type="button" role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}>
            {label}
          </button>
        ))}
      </div>
      {pay.items.length > 0 ? (
        <div className="g-table-wrap">
          <table className="g-table">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Weg</th>
                <th className="g-num">Betrag</th>
                <th className="g-num">Euro-Wert</th>
                <th>Kunde/Auftrag</th>
                <th>Transaktion</th>
                <th>Status</th>
                <th>Aktion</th>
              </tr>
            </thead>
            <tbody>
              {pay.items.map((p) => (
                <PaymentRow key={String(p.paymentId)} p={p} offers={offers} />
              ))}
            </tbody>
          </table>
        </div>
      ) : note ? (
        <p className="g-note">{note}</p>
      ) : null}
      {pay.error ? (
        <p className="g-note" role="alert">
          {pay.error}
        </p>
      ) : null}
      {pay.more ? (
        <div className="g-actions">
          <button type="button" className="g-button" disabled={pay.loading} onClick={() => void pay.loadOlder()}>
            Ältere laden
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Ein Gutschein: Code nur hier (nie im Verlauf); bestätigt erst mit dem auf amazon.de tatsächlich
 *  eingelösten Betrag (Befehl 42). Darkfluenzer meldet sich nie bei Amazon an. */
function VoucherRow({ v }: { v: Voucher }) {
  const cmd = useCommand();
  const [euros, setEuros] = useState("");
  const [reject, setReject] = useState(false);
  const cents = Math.round(Number(euros.replace(",", ".")) * 100);
  const valid = /^\d+([.,]\d{1,2})?$/.test(euros.trim()) && cents > 0;
  const [label, tone] = VOUCHER_STATUS[v.status] ?? [v.status, "neutral" as Tone];
  return (
    <tr>
      <td className="g-nowrap">{dateTime(v.atMs)}</td>
      <td>
        <button
          type="button"
          className="g-row"
          title="Kundenakte öffnen"
          onClick={() => {
            openRegister(v.customerId);
            window.location.hash = "#nachrichten";
          }}
        >
          {v.displayName || v.customerNo}
        </button>
      </td>
      <td className="g-mono">{v.code}</td>
      <td>
        <span className="g-badge" data-tone={tone}>
          {label}
        </span>
        {v.status === "redeemed" ? ` ${EUR.format(v.amountCents / 100)}` : ""}
        {v.decidedMs ? <small> · {dateTime(v.decidedMs)}</small> : null}
      </td>
      <td>
        {v.status === "pending" ? (
          <span className="g-value">
            <input
              className="g-input"
              inputMode="decimal"
              aria-label="Eingelöster Betrag in Euro"
              placeholder="eingelöst €"
              value={euros}
              onChange={(e) => setEuros(e.target.value)}
            />
            <button
              type="button"
              className="g-button g-primary"
              disabled={!valid || cmd.pending}
              onClick={() => void cmd.run({ case: "giftCardConfirm", value: { voucherId: v.voucherId, amountCents: cents } }, { done: "Eingelöst." })}
            >
              Eingelöst
            </button>
            {reject ? (
              <button
                type="button"
                className="g-button g-danger"
                disabled={cmd.pending}
                onClick={() => void cmd.run({ case: "giftCardConfirm", value: { voucherId: v.voucherId, reject: true } }, { done: "Abgelehnt." })}
              >
                Wirklich ablehnen
              </button>
            ) : (
              <button type="button" className="g-button" onClick={() => setReject(true)}>
                Ablehnen
              </button>
            )}
          </span>
        ) : null}
        {cmd.notice ? <small role="alert">{cmd.notice}</small> : null}
      </td>
    </tr>
  );
}

function Vouchers({ vouchers }: { vouchers: readonly Voucher[] }) {
  const open = vouchers.filter((v) => v.status === "pending").length;
  return (
    <div className="g-section">
      <div className="g-between">
        <h2>Gutscheine zu prüfen</h2>
        <span className="g-badge" data-tone={open ? "warn" : "neutral"}>
          {open} OFFEN
        </span>
      </div>
      <small>Auf amazon.de im Konto der Influencerin einlösen, dann den tatsächlich eingelösten Betrag eintragen.</small>
      {vouchers.length > 0 ? (
        <div className="g-table-wrap">
          <table className="g-table">
            <thead>
              <tr>
                <th>Erhalten</th>
                <th>Kunde</th>
                <th>Code</th>
                <th>Status</th>
                <th>Aktion</th>
              </tr>
            </thead>
            <tbody>
              {vouchers.map((v) => (
                <VoucherRow key={String(v.voucherId)} v={v} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="g-note">Keine Gutscheine.</p>
      )}
    </div>
  );
}

/** Steuer-Monatsliste (V0 §8.5 Punkt 7): CSV mit Euro-Wert und Kurs je Eingang. */
function MonthExport() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const valid = /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
  return (
    <div className="g-section">
      <h2>Monatsliste</h2>
      <span className="g-actions">
        <input className="g-input g-input-auto" type="month" aria-label="Monat" value={month} onChange={(e) => setMonth(e.target.value)} />
        {valid ? (
          <a className="g-button g-nowrap" href={`/api/v1/payment-export/${month}`} download>
            Monatsliste herunterladen
          </a>
        ) : (
          <small>Monat wählen</small>
        )}
      </span>
      <small>Alle Eingänge des Monats (UTC) mit Euro-Wert, Kurs und Kurszeit beim Eingang.</small>
    </div>
  );
}

export function Wallet() {
  const wallet = useStateTopic(Topic.WALLET);
  const accounts = wallet?.value.accounts ?? [];
  const sources = wallet?.value.sources ?? [];
  const vouchers = wallet?.value.vouchers ?? [];
  const offers = wallet?.value.openOffers ?? [];
  const pendingVouchers = vouchers.filter((v) => v.status === "pending").length;
  const stale = (wallet?.staleSince ?? null) !== null;
  const [openKey, setOpenKey] = useState<string | null>(null);
  const open = accounts.find((a) => a.key === openKey);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (openKey && !open) dialog.current?.close(); // Konto nicht mehr im Backendzustand
  }, [openKey, open]);

  function show(key: string) {
    setOpenKey(key);
    dialog.current?.showModal();
  }

  return (
    <section className="g-panel">
      <div className="g-between">
        <h1>Wallet</h1>
        <SourcesBadge sources={sources} has={!!wallet} staleSince={wallet?.staleSince ?? null} />
      </div>
      <p className="g-lead">Zahlungseingänge und Guthaben · nur beobachtet</p>

      <div className="g-cards">
        {accounts.map((a) => (
          <AccountCard key={a.key} a={a} stale={stale} onOpen={() => show(a.key)} />
        ))}
        <div className="g-card g-account">
          <span className="g-account-head">Amazon-Gutscheine</span>
          <strong className="g-account-value">{pendingVouchers}</strong>
          <small>zu prüfen · Einlösen manuell auf amazon.de</small>
          <span className="g-account-badges">
            <span className="g-badge" data-tone={pendingVouchers ? "warn" : "neutral"}>
              MANUELL
            </span>
          </span>
        </div>
        {NOT_CONNECTED.filter(([key]) => !accounts.some((a) => a.key === key)).map(([key, title, note]) => (
          <div key={key} className="g-card g-account">
            <span className="g-account-head">{title}</span>
            <strong className="g-account-value">–</strong>
            <small>{note}</small>
            <span className="g-account-badges">
              <span className="g-badge">NICHT EINGERICHTET</span>
            </span>
          </div>
        ))}
      </div>
      {wallet ? null : <p className="g-note">Keine Kontodaten.</p>}

      <Payments offers={offers} />
      <Vouchers vouchers={vouchers} />
      <MonthExport />

      <div className="g-section">
        <details className="g-expert">
          <summary>Technische Details</summary>
          {sources.length > 0 ? (
            sources.map((s) => (
              <div key={s.name} className="g-stack">
                <span className="g-between">
                  <strong>{s.name}</strong>
                  <small>{s.okMs ? `zuletzt erfolgreich ${dateTime(s.okMs)}` : "noch keine erfolgreiche Abfrage"}</small>
                </span>
                <small className="g-mono">{s.url || "–"}</small>
                {s.error ? <span className="g-error">{s.error}</span> : null}
              </div>
            ))
          ) : (
            <p className="g-note">{wallet ? "Keine Datenquellen eingerichtet." : "Keine Daten."}</p>
          )}
        </details>
      </div>

      <dialog ref={dialog} className="g-drawer" aria-labelledby="wallet-account" onClose={() => setOpenKey(null)}>
        {open ? <AccountDetail key={open.key} a={open} stale={stale} onClose={() => dialog.current?.close()} /> : null}
      </dialog>
    </section>
  );
}
