import { fromBinary, type DescMessage, type MessageShape } from "@bufbuild/protobuf";
import { useSyncExternalStore } from "react";
import {
  ComfyStatusSchema,
  JobCompletedSchema,
  JobsActiveSchema,
  WorkflowsSchema,
} from "./generated/darkfluenzer/v1/comfy_pb";
import { MediaItemSchema, MediaRemovedSchema } from "./generated/darkfluenzer/v1/media_pb";
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
  [Topic.COMFY_STATUS]: { cls: TopicClass.STATE, schema: ComfyStatusSchema },
  [Topic.JOBS_ACTIVE]: { cls: TopicClass.STATE, schema: JobsActiveSchema },
  [Topic.COMFY_WORKFLOWS]: { cls: TopicClass.STATE, schema: WorkflowsSchema },
  [Topic.JOB_COMPLETED]: { cls: TopicClass.EVENT, schema: JobCompletedSchema },
  [Topic.MEDIA_ADDED]: { cls: TopicClass.EVENT, schema: MediaItemSchema },
  [Topic.MEDIA_REMOVED]: { cls: TopicClass.EVENT, schema: MediaRemovedSchema },
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
  return { subscribe };
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
