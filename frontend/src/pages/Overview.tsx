import { PLATFORM_LABEL, customerName, openRegister, shortTime, useCustomers } from "../core/channels";
import { Topic } from "../core/generated/darkfluenzer/v1/stream_pb";
import { useStateTopic } from "../core/state";
import { clock } from "./ComfyUI";

const RECENT_CUSTOMERS = 8;

// Übersicht (F7.1): Informationskarten nur aus echtem Backendzustand; ein Klick auf einen Kunden
// öffnet dessen Kundenakte im Reiter Nachrichten. „Freigaben ausstehend“ zählt die Aufträge, deren
// Stufe auf eine Betreiberentscheidung wartet (STATE orders.active); Kundenfreigaben folgen mit C5.
export function Overview() {
  const active = useStateTopic(Topic.JOBS_ACTIVE);
  const jobs = active?.value.jobs ?? [];
  const running = jobs.find((j) => j.running);
  const stale = active?.staleSince ?? null;
  const customers = useCustomers();
  const files = customers.list.filter((c) => c.kind === "customer");
  const unread = files.reduce((n, c) => n + c.unread, 0);
  const recent = files.slice(0, RECENT_CUSTOMERS);
  const orders = useStateTopic(Topic.ORDERS_ACTIVE);
  const deciding = (orders?.value.orders ?? []).filter((o) => o.stages.some((st) => st.status === "waiting"));
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
          <small>
            {running ? `läuft: ${running.jobId ? running.workflow : "Auftrag aus der ComfyUI-Oberfläche"}` : jobs.length ? "wartet" : "leer"}
            {active?.value.paused.length ? ` · angehalten: ${active.value.paused.join(", ")}` : ""}
            {stale !== null ? ` · veraltet seit ${clock(stale)}` : ""}
          </small>
        </div>
        <div className="g-card g-kpi" data-stale={(orders?.staleSince ?? null) !== null || undefined}>
          <small>Freigaben ausstehend</small>
          <strong>{orders ? deciding.length : "–"}</strong>
          <small>{deciding.length ? `Kandidatenauswahl: ${deciding.map((o) => o.orderNo).join(", ")}` : orders ? "keine Entscheidung offen" : "keine Daten"}</small>
        </div>
      </div>
      <div className="g-section">
        <h2>Aktuelle Kunden · anklicken zum Öffnen</h2>
        {recent.map((c) => (
          <button
            key={String(c.customerId)}
            type="button"
            className="g-line g-row"
            onClick={() => {
              openRegister(c.customerId);
              window.location.hash = "#nachrichten";
            }}
          >
            <strong className="g-ellipsis">{c.displayName ? `${customerName(c)} · ${c.customerNo}` : c.customerNo}</strong>
            <span className="g-value">
              {c.lastMs ? `${PLATFORM_LABEL[c.lastPlatform] ?? c.lastPlatform} · ${shortTime(c.lastMs)}` : "Noch keine Nachricht"}
              {c.unread ? <span className="g-unread">{c.unread}</span> : null}
            </span>
          </button>
        ))}
        {recent.length === 0 ? <p className="g-note">{customers.loaded ? "Noch keine Kunden." : customers.error || "Keine Daten"}</p> : null}
      </div>
    </section>
  );
}
