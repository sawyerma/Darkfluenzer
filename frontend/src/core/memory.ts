import { fromBinary } from "@bufbuild/protobuf";
import { MemoryPageSchema, type MemoryPage } from "./generated/darkfluenzer/v1/memory_pb";
import { protectedGet } from "./media";

/** Gedächtnis eines Bereichs (SP4 Schritt 5) samt Verlauf; mit ``query`` die Auswahl für den nächsten
 *  Lauf (Kontextinspektor). Bei Aufruf geladen, Änderungen kommen als EVENT 32. */
export async function fetchMemory(scope: string, owner: bigint, session: number, query = ""): Promise<MemoryPage> {
  const q = new URLSearchParams({ scope, owner: String(owner), session: String(session) });
  if (query.trim()) q.set("query", query.trim());
  const resp = await protectedGet(`/api/v1/memory-page?${q.toString()}`);
  return fromBinary(MemoryPageSchema, new Uint8Array(await resp.arrayBuffer()));
}
