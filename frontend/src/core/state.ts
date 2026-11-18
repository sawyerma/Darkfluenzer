import { fromBinary, type DescMessage, type MessageShape } from "@bufbuild/protobuf";
import { useSyncExternalStore } from "react";
import {
  ComfyInstancesSchema,
  JobCompletedSchema,
  JobsActiveSchema,
  ResourcesSchema,
  WorkflowsSchema,
} from "./generated/darkfluenzer/v1/comfy_pb";
import { ChannelsSchema, ConversationEventSchema, CustomerUpdatedSchema } from "./generated/darkfluenzer/v1/channel_pb";
import { CharactersSchema } from "./generated/darkfluenzer/v1/character_pb";
import { InfluencersSchema } from "./generated/darkfluenzer/v1/influencer_pb";
import { OrdersActiveSchema, OrderUpdatedSchema } from "./generated/darkfluenzer/v1/order_pb";
import { CommandReceiptSchema, type CommandReceipt } from "./generated/darkfluenzer/v1/commands_pb";
import { MediaItemSchema, MediaRemovedSchema } from "./generated/darkfluenzer/v1/media_pb";
import { PaymentUpdatedSchema, WalletSchema } from "./generated/darkfluenzer/v1/wallet_pb";
import { AiResultSchema, AiStatusSchema } from "./generated/darkfluenzer/v1/ai_pb";
import {
  Topic,
  TopicClass,
  type CatchupComplete,
  type Event,
  type StateFull,
  type TopicDescriptor,
} from "./generated/darkfluenzer/v1/stream_pb";

// Topic-Bindung des Frontends; muss mit den Deskriptoren im Welcome übereinstimmen.
const TOPICS = {
  [Topic.COMFY_INSTANCES]: { cls: TopicClass.STATE, schema: ComfyInstancesSchema },
  [Topic.RESOURCES]: { cls: TopicClass.STATE, schema: ResourcesSchema },
  [Topic.JOBS_ACTIVE]: { cls: TopicClass.STATE, schema: JobsActiveSchema },
  [Topic.COMFY_WORKFLOWS]: { cls: TopicClass.STATE, schema: WorkflowsSchema },
  [Topic.CHARACTERS]: { cls: TopicClass.STATE, schema: CharactersSchema },
  [Topic.ORDERS_ACTIVE]: { cls: TopicClass.STATE, schema: OrdersActiveSchema },
  [Topic.CHANNELS]: { cls: TopicClass.STATE, schema: ChannelsSchema },
  [Topic.WALLET]: { cls: TopicClass.STATE, schema: WalletSchema },
  [Topic.INFLUENCERS]: { cls: TopicClass.STATE, schema: InfluencersSchema },
  [Topic.AI_STATUS]: { cls: TopicClass.STATE, schema: AiStatusSchema },
  [Topic.CUSTOMER_UPDATED]: { cls: TopicClass.EVENT, schema: CustomerUpdatedSchema },
  [Topic.CONVERSATION_EVENT]: { cls: TopicClass.EVENT, schema: ConversationEventSchema },
  [Topic.ORDER_UPDATED]: { cls: TopicClass.EVENT, schema: OrderUpdatedSchema },
  [Topic.JOB_COMPLETED]: { cls: TopicClass.EVENT, schema: JobCompletedSchema },
  [Topic.MEDIA_ADDED]: { cls: TopicClass.EVENT, schema: MediaItemSchema },
  [Topic.MEDIA_REMOVED]: { cls: TopicClass.EVENT, schema: MediaRemovedSchema },
  [Topic.COMMAND_RECEIPT]: { cls: TopicClass.EVENT, schema: CommandReceiptSchema },
  [Topic.PAYMENT_UPDATED]: { cls: TopicClass.EVENT, schema: PaymentUpdatedSchema },
  [Topic.AI_RESULT]: { cls: TopicClass.EVENT, schema: AiResultSchema },
} as const;

type Topics = typeof TOPICS;
type KnownTopic = keyof Topics & Topic;
type Payload<T extends KnownTopic> = MessageShape<Topics[T]["schema"]>;

export interface StateValue<V> {
  value: V;
  generation: bigint;
  seq: bigint;
  // Seit wann der Wert nicht mehr bestätigt ist (Verbindung unterbrochen); null = aktuell.
  staleSince: number | null;
}

export interface EventItem<V> {
  cursor: bigint;
  committedMs: number;
  value: V;
}

export interface EventLog<V> {
  items: readonly EventItem<V>[];
  lastCursor: bigint;
  live: boolean; // Nachzug abgeschlossen, Live-Ereignisse folgen
  gap: boolean; // ältere Ereignisse konnten nicht nachgeladen werden
}

const states = new Map<Topic, StateValue<unknown>>();
const events = new Map<Topic, EventLog<unknown>>();
const listeners = new Set<() => void>();
const receiptListeners = new Set<(r: CommandReceipt) => void>();
let offeredTopics: ReadonlySet<Topic> = new Set();

/** Persistierte Befehls-Receipts (EVENT command.receipt) beobachten; liefert die Abmeldung. */
export function onReceipt(fn: (r: CommandReceipt) => void): () => void {
  receiptListeners.add(fn);
  return () => receiptListeners.delete(fn);
}

function emit(): void {
  for (const fn of listeners) fn();
}

function decode<S extends DescMessage>(schema: S, payload: Uint8Array): MessageShape<S> {
  return fromBinary(schema, payload);
}

/** Prüft die angebotenen Topics gegen die eigene Bindung und liefert die Abonnements.
 *  Falsche Klasse oder Payload-Bindung -> Fehlertext (Verbindung wird blockiert). */
export function acceptTopics(
  offered: readonly TopicDescriptor[],
): { subscribe: { topic: Topic; afterCursor: bigint }[] } | { error: string } {
  const subscribe: { topic: Topic; afterCursor: bigint }[] = [];
  for (const d of offered) {
    const local = TOPICS[d.topic as KnownTopic];
    if (!local) continue; // neueres Backend-Topic, das dieses Frontend nicht anzeigt
    if (local.cls !== d.topicClass || local.schema.typeName !== d.payloadType) {
      return { error: `Topic ${Topic[d.topic]}: Bindung ${d.payloadType} passt nicht` };
    }
    subscribe.push({ topic: d.topic, afterCursor: events.get(d.topic)?.lastCursor ?? 0n });
  }
  offeredTopics = new Set(subscribe.map((s) => s.topic));
  return { subscribe };
}

/** Bietet das verbundene Backend dieses Topic an (letztes Welcome)? */
export function topicOffered(topic: Topic): boolean {
  return offeredTopics.has(topic);
}

/** STATE: ältere (generation, seq) verwerfen. Gleicher Stand (Snapshot nach Reconnect)
 *  bestätigt den Wert und hebt "veraltet" auf. */
export function applyState(f: StateFull): boolean {
  const local = TOPICS[f.topic as KnownTopic];
  if (!local || local.cls !== TopicClass.STATE) return false;
  const old = states.get(f.topic);
  if (old && (f.generation < old.generation || (f.generation === old.generation && f.seq < old.seq))) {
    return false;
  }
  states.set(f.topic, {
    value: decode(local.schema, f.payload),
    generation: f.generation,
    seq: f.seq,
    staleSince: null,
  });
  emit();
  return true;
}

/** EVENT: Cursor streng steigend; bereits angewendete Cursor sind Duplikate. */
export function applyEvent(e: Event): boolean {
  const local = TOPICS[e.topic as KnownTopic];
  if (!local || local.cls !== TopicClass.EVENT) return false;
  const log = events.get(e.topic) ?? { items: [], lastCursor: 0n, live: false, gap: false };
  if (e.cursor <= log.lastCursor) return false;
  const item = { cursor: e.cursor, committedMs: Number(e.committedUnixMs), value: decode(local.schema, e.payload) };
  events.set(e.topic, { ...log, items: [...log.items, item], lastCursor: e.cursor });
  emit();
  if (e.topic === Topic.COMMAND_RECEIPT) for (const fn of receiptListeners) fn(item.value as CommandReceipt);
  return true;
}

/** Ende des Nachzugs. Liegt der Journal-Kopf unter dem eigenen Cursor, wurde das Journal
 *  ersetzt: lokaler Stand wird verworfen, der nächste Abonnementlauf beginnt neu. */
export function catchupComplete(c: CatchupComplete): void {
  const log = events.get(c.topic) ?? { items: [], lastCursor: 0n, live: false, gap: false };
  if (c.through < log.lastCursor) {
    events.set(c.topic, { items: [], lastCursor: 0n, live: false, gap: true });
  } else {
    events.set(c.topic, { ...log, live: true, gap: log.gap || c.gap });
  }
  emit();
}

/** Verbindung verloren: alle Werte bleiben sichtbar, gelten aber als veraltet. */
export function markStale(): void {
  const now = Date.now();
  for (const [topic, s] of states) if (s.staleSince === null) states.set(topic, { ...s, staleSince: now });
  for (const [topic, l] of events) if (l.live) events.set(topic, { ...l, live: false });
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function stateOf<T extends KnownTopic>(topic: T): StateValue<Payload<T>> | undefined {
  return states.get(topic) as StateValue<Payload<T>> | undefined;
}

export function eventLogOf<T extends KnownTopic>(topic: T): EventLog<Payload<T>> | undefined {
  return events.get(topic) as EventLog<Payload<T>> | undefined;
}

export function useStateTopic<T extends KnownTopic>(topic: T): StateValue<Payload<T>> | undefined {
  return useSyncExternalStore(subscribe, () => stateOf(topic));
}

export function useEventTopic<T extends KnownTopic>(topic: T): EventLog<Payload<T>> | undefined {
  return useSyncExternalStore(subscribe, () => eventLogOf(topic));
}
