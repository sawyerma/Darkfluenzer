import { INSTANCE_LABEL, STAGE_LABEL, STATE_LABEL, clock } from "./comfyui/common";
import { PLATFORM_LABEL, customerName, openRegister, shortTime, useCustomers } from "../core/channels";
import { SUPPORTED, channelBadge } from "./messages/Channels";
import type { ActiveOrder } from "../core/generated/darkfluenzer/v1/order_pb";
import { ComfyState } from "../core/generated/darkfluenzer/v1/comfy_pb";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import type { Tone } from "./messages/common";
import { useStateTopic } from "../core/state";

const RECENT_CUSTOMERS = 8;
const OPEN_ORDERS = 8;

const SOURCE_LABEL: Record<string, string> = { operator: "Betreiber", cloner: "Kloner", customer: "Kunde" };
const KIND_LABEL: Record<string, string> = { image: "Foto", video: "Video" };

type OrderRow = { order: ActiveOrder; badge: [string, Tone]; detail: string; customer: boolean };

function openCustomer(id: bigint) {
  openRegister(id);
  window.location.hash = "#nachrichten";
}

function origin(o: ActiveOrder): string {
  const who = o.source === "customer" ? o.customerNo : (SOURCE_LABEL[o.source] ?? o.source);
  return [who, KIND_LABEL[o.kind] ?? o.kind].filter(Boolean).join(" · ");
}

// Übersicht (F7.1, FRONT §3.1, GUI-Prüfung 18.11. Punkt 5): Kennzahlen und Listen nur aus echtem
// Backendzustand (STATE jobs.active, orders.active, comfy.instances, channels, resources). Offene
// Entscheidungen: Kundenfreigaben (review), bezahlte Aufträge vor der Produktion, Kandidatenauswahl
// (BUG-070); ein Klick öffnet die Kundenakte bzw. den Reiter ComfyUI.
export function Overview() {
  const active = useStateTopic(Topic.JOBS_ACTIVE);
  const jobs = active?.value.jobs ?? [];
  const stale = active?.staleSince ?? null;
  const customers = useCustomers();
  const files = customers.list.filter((c) => c.kind === "customer");
  const unread = files.reduce((n, c) => n + c.unread, 0);
  const recent = files.slice(0, RECENT_CUSTOMERS);
  const orders = useStateTopic(Topic.ORDERS_ACTIVE);
  const producing = orders?.value.orders ?? [];
  const review = orders?.value.awaitingReview ?? [];
  const paid = orders?.value.awaitingProduction ?? [];
  const deciding = producing.filter((o) => o.stages.some((st) => st.status === "waiting"));
  const instances = useStateTopic(Topic.COMFY_INSTANCES);
  const channels = useStateTopic(Topic.CHANNELS);
  const resources = useStateTopic(Topic.RESOURCES)?.value;

  // GPU-Warteschlange je Instanz (aktiv, wartend, angehalten)
  const names = [...new Set([...(instances?.value.instances ?? []).map((i) => i.name), ...jobs.map((j) => j.instance)])].filter(Boolean);
  const queueLines = names.map((name) => {
    const own = jobs.filter((j) => j.instance === name);
    const run = own.find((j) => j.running);
    const waiting = own.length - (run ? 1 : 0);
    const parts = [
      run ? `läuft: ${run.jobId ? run.workflow : "Auftrag aus der ComfyUI-Oberfläche"}` : "",
      waiting ? `${waiting} wartend` : "",
      active?.value.paused.includes(name) ? "angehalten" : "",
    ].filter(Boolean);
    return `${INSTANCE_LABEL[name] ?? name}: ${parts.join(" · ") || "leer"}`;
  });

  // Betrieb: Instanzen und die Kanäle, die es heute gibt
  const services = [
    ...(instances?.value.instances ?? []).map((i) => {
      const [label, tone] = STATE_LABEL[i.state];
      return { name: (INSTANCE_LABEL[i.name] ?? i.name).split(" · ")[0], label, ok: tone === "ok" };
    }),
    ...(channels?.value.channels ?? [])
      .filter((c) => SUPPORTED.includes(c.platform))
      .map((c) => {
        const [label, tone] = channelBadge(c);
        return { name: PLATFORM_LABEL[c.platform] ?? c.platform, label, ok: tone === "ok" };
      }),
  ];
  const ready = services.filter((s) => s.ok).length;
  const busy = (instances?.value.instances ?? []).some((i) => i.state === ComfyState.BUSY);

  const rows: OrderRow[] = [
    ...review.map((o) => ({ order: o, badge: ["FREIGABE", "warn"] as [string, Tone], detail: `${origin(o)} · Ergebnis prüfen`, customer: true })),
    ...paid.map((o) => ({ order: o, badge: ["BEZAHLT", "warn"] as [string, Tone], detail: `${origin(o)} · wartet auf Produktion`, customer: true })),
    ...deciding.map((o) => ({ order: o, badge: STAGE_LABEL.waiting ?? ["AUSWAHL", "warn"], detail: `${origin(o)} · Kandidaten wählen`, customer: false })),
    ...producing
      .filter((o) => !deciding.includes(o))
      .map((o) => {
        const last = o.stages[o.stages.length - 1];
        return { order: o, badge: STAGE_LABEL[last?.status ?? ""] ?? ["IN PRODUKTION", "neutral"], detail: origin(o), customer: false };
      }),
  ];

  return (
    <section className="g-panel">
      <h1>Übersicht</h1>
      <p className="g-lead">Gemeinsamer Betrieb: alle Kanäle, alle Kunden, eine Renderwarteschlange.</p>
      <div className="g-cards">
        <div className="g-card g-kpi" data-stale={!customers.live || undefined}>
          <small>Kundenakten</small>
          <strong>{customers.loaded ? files.length : "–"}</strong>
          <small>
            {customers.loaded ? (unread ? `${unread} ungelesen` : "keine ungelesenen Nachrichten") : customers.error || "keine Daten"}
            {customers.loaded && !customers.live ? " · veraltet" : ""}
          </small>
        </div>
        <div className="g-card g-kpi" data-stale={stale !== null || undefined}>
          <small>GPU-Warteschlange</small>
          <strong>{active ? jobs.length : "–"}</strong>
          {active ? queueLines.map((line) => <small key={line}>{line}</small>) : <small>keine Daten</small>}
          {stale !== null ? <small>veraltet seit {clock(stale)}</small> : null}
        </div>
        <div className="g-card g-kpi" data-stale={(orders?.staleSince ?? null) !== null || undefined}>
          <small>Freigaben ausstehend</small>
          <strong>{orders ? review.length + paid.length + deciding.length : "–"}</strong>
          <small>{orders ? `Freigabe ${review.length} · wartet auf Produktion ${paid.length} · Auswahl ${deciding.length}` : "keine Daten"}</small>
        </div>
        <div className="g-card g-kpi" data-stale={(instances?.staleSince ?? channels?.staleSince ?? null) !== null || undefined}>
          <small>Betrieb</small>
          <strong>
            {services.length ? ready : "–"}
            {services.length ? <small> von {services.length} bereit</small> : null}
          </strong>
          <small>{services.length ? services.map((s) => `${s.name} ${s.label.toLowerCase()}`).join(" · ") : "keine Daten"}</small>
          <small>
            {resources?.ramTotalGb
              ? `Speicher ${Math.round(resources.ramFreeGb)} von ${Math.round(resources.ramTotalGb)} GB frei · Swap ${Math.round(resources.swapUsedMb)} MB${busy ? " · GPU arbeitet" : ""}`
              : "Speicher: keine Daten"}
            {" · "}
            <a className="g-link" href="#einstellungen">
              Einstellungen
            </a>
          </small>
        </div>
      </div>
      <div className="g-overview-lists">
        <div className="g-listpanel">
          <h2 className="g-listtitle">Offene Aufträge · anklicken zum Öffnen</h2>
          {rows.slice(0, OPEN_ORDERS).map(({ order: o, badge: [label, tone], detail, customer }) => (
            <button
              key={o.orderNo}
              type="button"
              className="g-listrow g-row"
              onClick={() => (customer ? openCustomer(o.customerId) : (window.location.hash = "#comfyui"))}
            >
              <strong className="g-ellipsis">{o.orderNo}</strong>
              <span className="g-value">
                <span className="g-ellipsis">{detail}</span>
                <span className="g-badge" data-tone={tone === "neutral" ? undefined : tone}>
                  {label}
                </span>
              </span>
            </button>
          ))}
          {rows.length > OPEN_ORDERS ? <p className="g-note">+{rows.length - OPEN_ORDERS} weitere im Reiter ComfyUI</p> : null}
          {rows.length === 0 ? <p className="g-note">{orders ? "Keine offenen Aufträge." : "Keine Daten"}</p> : null}
        </div>
        <div className="g-listpanel">
          <h2 className="g-listtitle">Aktuelle Kunden · anklicken zum Öffnen</h2>
          {recent.map((c) => (
            <button key={String(c.customerId)} type="button" className="g-listrow g-row" onClick={() => openCustomer(c.customerId)}>
              <strong className="g-ellipsis">{c.displayName ? `${customerName(c)} · ${c.customerNo}` : c.customerNo}</strong>
              <span className="g-value">
                {c.lastMs ? `${PLATFORM_LABEL[c.lastPlatform] ?? c.lastPlatform} · ${shortTime(c.lastMs)}` : "Noch keine Nachricht"}
                {c.unread ? <span className="g-unread">{c.unread}</span> : null}
              </span>
            </button>
          ))}
          {recent.length === 0 ? <p className="g-note">{customers.loaded ? "Noch keine Kunden." : customers.error || "Keine Daten"}</p> : null}
        </div>
      </div>
    </section>
  );
}
