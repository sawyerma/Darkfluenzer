import { Composer } from "./messages/Composer";
import { CustomerList, Registers } from "./messages/CustomerList";
import { CustomerPanel } from "./messages/CustomerPanel";
import type { CustomerSummary } from "../core/generated/darkfluenzer/v1/channel_pb";
import { DefaultPanel } from "./messages/DefaultPanel";
import { PLATFORMS, PLATFORM_LABEL, customerName, handleLabel, markRead, markReadTarget, useConversation, useCustomers, useRegisters } from "../core/channels";
import { type ReactNode, useEffect, useState } from "react";
import { Stream, useDocumentVisible } from "./messages/Stream";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { View } from "./messages/common";
import { useStateTopic } from "../core/state";

const READ_ONLY = "Gesamter Verlauf · nur lesen. Antworten ausschließlich im gewählten Kanal.";

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
          {/* WhatsApp folgt später (C7): Unterregister nur, wenn der Kunde dort schon verknüpft ist */}
          {PLATFORMS.filter((p) => p !== "whatsapp" || linked.has(p)).map((p) => (
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
    <section className="g-panel g-flush">
      <h1 className="g-sr-only">Nachrichten</h1>
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
