import { fromBinary } from "@bufbuild/protobuf";
import { useEffect, useMemo, useState } from "react";
import {
  MediaPageSchema,
  MediaProvenanceSchema,
  type MediaItem,
  type MediaPage,
  type MediaProvenance,
} from "./generated/darkfluenzer/v1/media_pb";
import { Topic } from "./generated/darkfluenzer/v1/stream_pb";
import { refreshSession, useConnection } from "./realtime";
import { useEventTopic } from "./state";

// Galerie (Medienindex des Backends): Seiten per Protobuf-GET auf Aufruf, neue und gelöschte
// Einträge als EVENT media.added / media.removed – kein Polling.

const PAGE_SIZE = 48;

/** Sitzungsgeschützter Pfad einer indizierten Datei (Pfad relativ zu local/). */
export function mediaUrl(path: string): string {
  return `/api/v1/media/${encodeURI(path)}`;
}

async function get(url: string): Promise<Response> {
  let resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (resp.status === 401) {
    await refreshSession();
    resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  }
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp;
}

/** Galerie-Seite, neueste zuerst; ``before`` = 0 beginnt bei der neuesten Datei. */
async function fetchMediaPage(before: bigint, limit: number): Promise<MediaPage> {
  const resp = await get(`/api/v1/media-page?before=${before}&limit=${limit}`);
  return fromBinary(MediaPageSchema, new Uint8Array(await resp.arrayBuffer()));
}

// Medien sind unveränderlich: ihre Herkunft wird je media_id genau einmal abgefragt und behalten
// (gleichzeitige Anfragen teilen sich eine; fehlgeschlagene werden beim nächsten Aufruf wiederholt).
const provenances = new Map<bigint, Promise<MediaProvenance>>();

export function fetchProvenance(mediaId: bigint): Promise<MediaProvenance> {
  let pending = provenances.get(mediaId);
  if (!pending) {
    pending = get(`/api/v1/provenance/${mediaId}`)
      .then(async (resp) => fromBinary(MediaProvenanceSchema, new Uint8Array(await resp.arrayBuffer())))
      .catch((e: unknown) => {
        provenances.delete(mediaId);
        throw e;
      });
    provenances.set(mediaId, pending);
  }
  return pending;
}

export type GalleryStatus = "ready" | "loading" | "offline";

/** Alle Galerie-Einträge, je media_id genau einer, neueste zuerst. Erste Seite beim Aufruf,
 *  ältere nur auf Wunsch; gelöschte (EVENT oder eigener angenommener Löschbefehl) fallen heraus. */
export function useGallery() {
  const live = useEventTopic(Topic.MEDIA_ADDED);
  const removed = useEventTopic(Topic.MEDIA_REMOVED);
  const connection = useConnection();
  const [pages, setPages] = useState<MediaItem[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [dropped, setDropped] = useState<ReadonlySet<bigint>>(new Set());

  const items = useMemo(() => {
    const byId = new Map<bigint, MediaItem>();
    for (const m of pages) byId.set(m.mediaId, m);
    for (const e of live?.items ?? []) byId.set(e.value.mediaId, e.value);
    for (const e of removed?.items ?? []) byId.delete(e.value.mediaId);
    for (const id of dropped) byId.delete(id);
    return [...byId.values()].sort((a, b) => (b.mediaId > a.mediaId ? 1 : b.mediaId < a.mediaId ? -1 : 0));
  }, [pages, live, removed, dropped]);

  async function load(before: bigint) {
    setLoading(true);
    setError("");
    try {
      const page = await fetchMediaPage(before, PAGE_SIZE);
      setPages((p) => [...p, ...page.items]);
      setMore(page.more);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (connection.status === "OPEN" && !loaded && !loading) void load(0n);
  }, [connection.status, loaded]);

  useEffect(() => {
    // Mehr Löschungen als der Nachzug liefert: neu laden statt veraltete Einträge zeigen
    if (removed?.gap) {
      setPages([]);
      setMore(false);
      setLoaded(false);
    }
  }, [removed?.gap]);

  const status: GalleryStatus = loaded || live?.live ? "ready" : connection.status === "OPEN" ? "loading" : "offline";
  return {
    items,
    more,
    loading,
    error,
    status,
    loadOlder: () => load(items.at(-1)?.mediaId ?? 0n),
    drop: (ids: bigint[]) => setDropped((s) => new Set([...s, ...ids])),
  };
}
