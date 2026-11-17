import { fromBinary } from "@bufbuild/protobuf";
import { useEffect, useMemo, useSyncExternalStore } from "react";
import {
  ConversationPageSchema,
  CustomerPageSchema,
  type ChannelIdentity,
  type ConversationEvent,
  type ConversationItem,
  type ConversationPage,
  type CustomerPage,
  type CustomerSummary,
  type CustomerUpdated,
  type DefaultContact,
} from "./generated/darkfluenzer/v1/channel_pb";
import { Topic } from "./generated/darkfluenzer/v1/stream_pb";
import { sendCommand } from "./commands";
import { protectedGet } from "./media";
import { useConnection, type ConnectionInfo } from "./realtime";
import { eventLogOf, topicOffered, useEventTopic, type EventItem, type EventLog } from "./state";

// Nachrichten-Cockpit (FRONT F4/F7.2–F7.4, V0 §5 DF-PUSH): Kundenliste und Verläufe als
// Protobuf-Seiten nur bei Aufruf und bei geänderter Version (neues EVENT des Bereichs, Reconnect);
// dazwischen werden die Live-Ereignisse customers.updated / conversations.event eingeblendet.
// Kein Polling. Gleiche Anfragen werden zusammengefasst, veraltete Antworten verworfen.

export type Platform = "instagram" | "telegram" | "whatsapp";
export const PLATFORMS: readonly Platform[] = ["instagram", "telegram", "whatsapp"];
export const PLATFORM_LABEL: Record<string, string> = {
  instagram: "Instagram",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  system: "System",
};
const PLATFORM_SHORT: Record<string, string> = { instagram: "IG", telegram: "TG", whatsapp: "WA" };

export function customerName(c: CustomerSummary): string {
  return c.displayName || c.customerNo || `Kunde ${c.customerId}`;
}

/** Kanalkennzeichen der Kundenliste: INTERN bzw. IG, TG, IG/TG … in fester Reihenfolge. */
export function platformTag(c: CustomerSummary): string {
  if (c.kind === "internal") return "INTERN";
  return PLATFORMS.filter((p) => c.platforms.includes(p))
    .map((p) => PLATFORM_SHORT[p])
    .join("/");
}

export function handleLabel(handle: string): string {
  return !handle || handle.startsWith("@") ? handle : `@${handle}`;
}

/** Uhrzeit heute, sonst Datum mit Uhrzeit; 0 = keine Zeit. */
export function shortTime(ms: bigint): string {
  if (!ms) return "";
  const d = new Date(Number(ms));
  const today = d.toDateString() === new Date().toDateString();
  return d.toLocaleString(
    "de-DE",
    today ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" },
  );
}

// ------------------------------------------------------------------ reine Zusammenführung

export interface Tagged<T> {
  value: T;
  // Journal-Cursor, ab dem dieser Stand gilt: bei Seiten der Cursor beim Absenden der Anfrage
  // (alle Ereignisse bis dahin sind enthalten), bei Ereignissen ihr eigener Cursor.
  tag: bigint;
}

const byItemId = (a: ConversationItem, b: ConversationItem) => (a.itemId < b.itemId ? -1 : a.itemId > b.itemId ? 1 : 0);

/** Kundenliste: Seite plus neuere Ereignisse (nur die ID = Akte entfernt). Default zuerst,
 *  dann nach letzter Aktivität. */
export function mergeCustomers(
  page: readonly CustomerSummary[],
  tag: bigint,
  events: readonly EventItem<CustomerUpdated>[],
): CustomerSummary[] {
  const byId = new Map(page.map((c) => [c.customerId, c] as const));
  for (const e of events) {
    const c = e.value.customer;
    if (e.cursor <= tag || !c) continue;
    if (c.kind) byId.set(c.customerId, c);
    else byId.delete(c.customerId);
  }
  return [...byId.values()].sort((a, b) => {
    if ((a.kind === "internal") !== (b.kind === "internal")) return a.kind === "internal" ? -1 : 1;
    if (a.lastMs !== b.lastMs) return a.lastMs > b.lastMs ? -1 : 1;
    return a.customerId > b.customerId ? -1 : a.customerId < b.customerId ? 1 : 0;
  });
}

/** Seiteneinträge übernehmen; ein schon bekannter Eintrag mit neuerem Stand bleibt. */
export function withPage(
  known: ReadonlyMap<bigint, Tagged<ConversationItem>>,
  items: readonly ConversationItem[],
  tag: bigint,
): Map<bigint, Tagged<ConversationItem>> {
  const next = new Map(known);
  for (const item of items) {
    const had = next.get(item.itemId);
    if (!had || had.tag <= tag) next.set(item.itemId, { value: item, tag });
  }
  return next;
}

/** Verlauf eines Kunden: geladene Seiten plus Live-Ereignisse, je item_id genau einmal,
 *  aufsteigend. Ein Ereignis ersetzt nur einen älteren Stand; neue Einträge vor der ältesten
 *  geladenen Seite bleiben weg, solange noch ältere Seiten existieren (keine Lücke im Verlauf). */
export function conversationItems(
  pages: ReadonlyMap<bigint, Tagged<ConversationItem>>,
  events: readonly EventItem<ConversationEvent>[],
  customerId: bigint,
  oldest: bigint,
  more: boolean,
): ConversationItem[] {
  const byId = new Map(pages);
  for (const e of events) {
    const item = e.value.item;
    if (!item || item.customerId !== customerId) continue;
    const had = byId.get(item.itemId);
    if (had ? had.tag < e.cursor : !more || item.itemId >= oldest) byId.set(item.itemId, { value: item, tag: e.cursor });
  }
  return [...byId.values()].map((t) => t.value).sort(byItemId);
}

/** Gelesen-Markierung: neuester ungelesener Eingang, bis zu dem alle ungelesenen Eingänge in
 *  der aktuellen Ansicht sichtbar sind (Kanal-Unterregister: nur dieser Kanal); 0 = nichts. */
export function markReadTarget(items: readonly ConversationItem[], platform: string | null): bigint {
  let upTo = 0n;
  for (const i of items) {
    if (i.direction !== "in" || i.read) continue;
    if (platform && i.platform !== platform) break;
    upTo = i.itemId;
  }
  return upTo;
}

/** Antwortziel im Kanal-Unterregister: genau eine Konversation dieser Plattform, sonst der Grund. */
export function replyTarget(identities: readonly ChannelIdentity[], platform: string): ChannelIdentity | string {
  const targets = identities.filter((i) => i.platform === platform && i.conversationId !== 0n);
  if (targets.length === 1) return targets[0]!;
  if (targets.length > 1) return "Mehrere Konversationen in diesem Kanal – Ziel nicht eindeutig";
  return identities.some((i) => i.platform === platform) ? "Noch keine Konversation in diesem Kanal" : "Kanal nicht verknüpft";
}

function latestCursorOf<T>(events: readonly EventItem<T>[], matches: (v: T) => boolean): bigint {
  for (let n = events.length - 1; n >= 0; n--) if (matches(events[n]!.value)) return events[n]!.cursor;
  return 0n;
}

/** Versionsgebundene Abfrage: je neuem Schlüssel genau eine Anfrage; Schlüsselwechsel während
 *  einer laufenden Anfrage ergeben danach genau eine Folgeanfrage für den neuesten Schlüssel.
 *  ``run`` meldet Fehler selbst und wirft nicht. */
export class VersionedQuery {
  private want = "";
  private done = "";
  private running = false;
  private readonly run: (key: string) => Promise<void>;

  constructor(run: (key: string) => Promise<void>) {
    this.run = run;
  }

  request(key: string): void {
    this.want = key;
    if (this.running || this.done === key) return;
    this.running = true;
    void this.run(key).finally(() => {
      this.done = key;
      this.running = false;
      this.request(this.want);
    });
  }
}

// ------------------------------------------------------------------ Laden

async function fetchCustomerPage(): Promise<CustomerPage> {
  const resp = await protectedGet("/api/v1/customer-page");
  return fromBinary(CustomerPageSchema, new Uint8Array(await resp.arrayBuffer()));
}

async function fetchConversationPage(customerId: bigint, before: bigint): Promise<ConversationPage> {
  const older = before ? `&before=${before}` : "";
  const resp = await protectedGet(`/api/v1/conversation-page?customer=${customerId}${older}`);
  return fromBinary(ConversationPageSchema, new Uint8Array(await resp.arrayBuffer()));
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const lastCursor = (log: EventLog<unknown> | undefined) => log?.lastCursor ?? 0n;

let tick = 0;
const listeners = new Set<() => void>();
function changed(): void {
  tick += 1;
  for (const fn of listeners) fn();
}
function useTick(): number {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => tick,
  );
}

/** Bereit für eine versionsgebundene Abfrage: verbunden und – falls das Backend das Topic
 *  anbietet – dessen Nachzug abgeschlossen (sonst würde jeder Nachzugsschritt abfragen). */
function caughtUp(connection: ConnectionInfo, topic: Topic, log: EventLog<unknown> | undefined): boolean {
  return connection.status === "OPEN" && (!topicOffered(topic) || log?.live === true);
}

// ------------------------------------------------------------------ Register (geöffnete Akten)

const REGISTER_KEY = "darkfluenzer.registers"; // nur Kunden-IDs, keine Kundendaten
let openIds: readonly bigint[] = [];
let activeId = 0n; // 0 = erstes Register (Default)
let knownIds: Set<bigint> | null = null;

try {
  const [active = "0", open = ""] = (sessionStorage.getItem(REGISTER_KEY) ?? "").split("|");
  activeId = BigInt(active || "0");
  openIds = open ? open.split(",").map((id) => BigInt(id)) : [];
} catch {
  // kein Browser-Speicher (Test, privates Fenster): leer beginnen
}

function saveRegisters(): void {
  try {
    sessionStorage.setItem(REGISTER_KEY, `${activeId}|${openIds.join(",")}`);
  } catch {
    // ohne Speicher gelten die Register nur bis zum Neuladen
  }
  changed();
}

/** Register öffnen bzw. aktivieren (Kundenliste, Übersicht). */
export function openRegister(id: bigint): void {
  if (!openIds.includes(id)) openIds = [...openIds, id];
  activeId = id;
  saveRegisters();
}

/** Register schließen: beendet weder Gespräch noch KI noch Queue. */
export function closeRegister(id: bigint): void {
  openIds = openIds.filter((x) => x !== id);
  if (activeId === id) activeId = 0n;
  saveRegisters();
}

export function useRegisters(): { open: readonly bigint[]; active: bigint } {
  useTick();
  return { open: openIds, active: activeId };
}

/** Register, die sich ohne Fokuswechsel öffnen (FRONT F4 Punkt 2): beim ersten Stand jede
 *  Kundenakte mit Ungelesenem (Neuladen, Erstkontakt während das Cockpit zu war – der Backend-Stand
 *  ist die Autorität), danach jede neu erscheinende Kundenakte. */
export function autoRegisters(
  list: readonly CustomerSummary[],
  known: ReadonlySet<bigint> | null,
  open: readonly bigint[],
): bigint[] {
  const pick = known === null ? list.filter((c) => c.unread > 0) : list.filter((c) => !known.has(c.customerId));
  return pick.filter((c) => c.kind === "customer" && !open.includes(c.customerId)).map((c) => c.customerId);
}

function noteCustomers(list: readonly CustomerSummary[]): void {
  const add = autoRegisters(list, knownIds, openIds);
  knownIds = new Set([...(knownIds ?? []), ...list.map((c) => c.customerId)]);
  if (add.length > 0) {
    openIds = [...openIds, ...add];
    saveRegisters();
  }
}

// ------------------------------------------------------------------ Kundenliste

const customers = { page: [] as readonly CustomerSummary[], tag: 0n, loaded: false, error: "" };
const customerQuery = new VersionedQuery(async () => {
  const tag = lastCursor(eventLogOf(Topic.CUSTOMER_UPDATED));
  try {
    const page = await fetchCustomerPage();
    Object.assign(customers, { page: page.customers, tag, loaded: true, error: "" });
  } catch (e) {
    customers.error = errorText(e);
  }
  changed();
});

/** Alle Kundenakten; neu abgefragt bei jedem neuen customers.updated, nach Reconnect und Lücke. */
export function useCustomers() {
  useTick();
  const connection = useConnection();
  const log = useEventTopic(Topic.CUSTOMER_UPDATED);
  const key = caughtUp(connection, Topic.CUSTOMER_UPDATED, log) ? `${connection.opened}#${lastCursor(log)}` : "";
  useEffect(() => {
    if (key) customerQuery.request(key);
  }, [key]);
  const { page, tag, loaded } = customers;
  const list = useMemo(() => (loaded ? mergeCustomers(page, tag, log?.items ?? []) : []), [page, tag, loaded, log]);
  useEffect(() => {
    if (loaded) noteCustomers(list);
  }, [list, loaded]);
  return { list, loaded, error: customers.error, live: connection.status === "OPEN" };
}

// ------------------------------------------------------------------ Verlauf je Kundenakte

interface Conversation {
  items: ReadonlyMap<bigint, Tagged<ConversationItem>>;
  oldest: bigint; // kleinste geladene item_id (0 = keine)
  more: boolean; // ältere Einträge vor ``oldest`` vorhanden
  identities: readonly ChannelIdentity[];
  defaultContact: DefaultContact | undefined;
  infoTag: bigint;
  epoch: number; // Verbindung (ConnectionInfo.opened), aus der die Seiten stammen
  loaded: boolean;
  error: string;
  olderLoading: boolean;
  query: VersionedQuery;
}

const conversations = new Map<bigint, Conversation>();

function applyPage(c: Conversation, page: ConversationPage, tag: bigint, older: boolean): void {
  c.items = withPage(c.items, page.items, tag);
  if (older || c.oldest === 0n) {
    c.oldest = page.items[0]?.itemId ?? c.oldest;
    c.more = page.more;
  }
  // Antwortziele (Revisionen) und Default-Felder nur aus der neuesten Seite, nie aus älteren
  if (!older && tag >= c.infoTag) {
    c.identities = page.identities;
    c.defaultContact = page.defaultContact;
    c.infoTag = tag;
  }
}

function conversationOf(customerId: bigint): Conversation {
  const known = conversations.get(customerId);
  if (known) return known;
  const c: Conversation = {
    items: new Map(),
    oldest: 0n,
    more: false,
    identities: [],
    defaultContact: undefined,
    infoTag: 0n,
    epoch: -1,
    loaded: false,
    error: "",
    olderLoading: false,
    query: new VersionedQuery(async (key) => {
      const epoch = Number(key.split("#")[0]);
      const tag = lastCursor(eventLogOf(Topic.CONVERSATION_EVENT));
      try {
        const page = await fetchConversationPage(customerId, 0n);
        if (c.epoch !== epoch) {
          // neue Verbindung (Reconnect, Lücke, ersetztes Journal): nur noch die frische Seite
          Object.assign(c, { items: new Map(), oldest: 0n, more: false, infoTag: 0n, epoch });
        }
        applyPage(c, page, tag, false);
        Object.assign(c, { loaded: true, error: "" });
      } catch (e) {
        c.error = errorText(e);
      }
      changed();
    }),
  };
  conversations.set(customerId, c);
  return c;
}

async function loadOlder(customerId: bigint): Promise<void> {
  const c = conversationOf(customerId);
  if (c.olderLoading || !c.more || c.oldest === 0n) return;
  const { epoch } = c;
  const tag = lastCursor(eventLogOf(Topic.CONVERSATION_EVENT));
  c.olderLoading = true;
  changed();
  try {
    const page = await fetchConversationPage(customerId, c.oldest);
    if (c.epoch === epoch) applyPage(c, page, tag, true);
  } catch (e) {
    c.error = errorText(e);
  } finally {
    c.olderLoading = false;
    changed();
  }
}

/** Verlauf, Antwortziele und ggf. Default-Felder einer Kundenakte. Neu abgefragt beim Öffnen,
 *  bei jedem neuen Ereignis dieses Kunden (u. a. neue Gesprächsrevision) und nach Reconnect. */
export function useConversation(customerId: bigint) {
  useTick();
  const connection = useConnection();
  const log = useEventTopic(Topic.CONVERSATION_EVENT);
  const customerLog = useEventTopic(Topic.CUSTOMER_UPDATED);
  const c = conversationOf(customerId);
  const events = log?.items;
  const ready =
    caughtUp(connection, Topic.CONVERSATION_EVENT, log) && caughtUp(connection, Topic.CUSTOMER_UPDATED, customerLog);
  const version = `${latestCursorOf(events ?? [], (v) => v.item?.customerId === customerId)}:${latestCursorOf(
    customerLog?.items ?? [],
    (v) => v.customer?.customerId === customerId,
  )}`;
  const key = ready ? `${connection.opened}#${version}` : "";
  useEffect(() => {
    if (key) c.query.request(key);
  }, [key, c]);
  const { loaded, items: pages, oldest, more } = c;
  const items = useMemo(
    () => (loaded ? conversationItems(pages, events ?? [], customerId, oldest, more) : []),
    [loaded, pages, events, customerId, oldest, more],
  );
  return {
    items,
    loaded,
    more,
    error: c.error,
    identities: c.identities,
    defaultContact: c.defaultContact,
    olderLoading: c.olderLoading,
    stale: connection.status !== "OPEN" || c.epoch !== connection.opened,
    loadOlder: () => void loadOlder(customerId),
  };
}

// ------------------------------------------------------------------ Gelesen

const readUpTo = new Map<bigint, bigint>();

/** Gelesen bis ``upTo`` – je Kunde nur für einen neueren Eingang als zuletzt gemeldet. */
export function markRead(customerId: bigint, upTo: bigint): void {
  if (upTo === 0n || (readUpTo.get(customerId) ?? 0n) >= upTo) return;
  readUpTo.set(customerId, upTo);
  void sendCommand({ case: "markRead", value: { customerId, upToItem: upTo } });
}
