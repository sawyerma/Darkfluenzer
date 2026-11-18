import { ChannelLines } from "./Channels";
import type { CustomerSummary } from "../../core/generated/darkfluenzer/v1/channel_pb";
import { PLATFORM_LABEL, closeRegister, customerName, openRegister, platformTag, shortTime } from "../../core/channels";
import { Topic } from "../../core/generated/darkfluenzer/v1/stream_pb";
import { useState } from "react";
import { useStateTopic } from "../../core/state";

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
export function CustomerList({
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
      <ChannelLines channels={channels?.value.channels} stale={!live || (channels?.staleSince ?? null) !== null} />
    </div>
  );
}

/** Geöffnete Kundenregister (F7.3): mehrere offen, × schließt nur das Register; Default bleibt. */
export function Registers({ tabs, activeId }: { tabs: readonly CustomerSummary[]; activeId: bigint }) {
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
