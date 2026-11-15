import { create, type MessageInitShape } from "@bufbuild/protobuf";
import { expect, test } from "vitest";
import {
  ChannelIdentitySchema,
  ConversationEventSchema,
  ConversationItemSchema,
  CustomerSummarySchema,
  CustomerUpdatedSchema,
} from "../src/core/generated/darkfluenzer/v1/channel_pb";
import {
  VersionedQuery,
  conversationItems,
  markReadTarget,
  mergeCustomers,
  replyTarget,
  withPage,
} from "../src/core/channels";

const item = (init: MessageInitShape<typeof ConversationItemSchema>) =>
  create(ConversationItemSchema, { customerId: 1n, platform: "telegram", direction: "in", status: "received", ...init });
const event = (cursor: bigint, init: MessageInitShape<typeof ConversationItemSchema>) => ({
  cursor,
  committedMs: 0,
  value: create(ConversationEventSchema, { item: item(init) }),
});
const ids = (items: { itemId: bigint }[]) => items.map((i) => i.itemId);

test("Verlauf: je item_id genau einmal, aufsteigend; nur neuere Ereignisse ersetzen den Seitenstand", () => {
  // Seite angefragt bei Cursor 10: enthält alle Ereignisse bis 10
  const pages = withPage(new Map(), [item({ itemId: 5n }), item({ itemId: 7n, direction: "out", status: "sending" })], 10n);
  const events = [
    event(9n, { itemId: 7n, direction: "out", status: "queued" }), // älter als die Seite
    event(11n, { itemId: 7n, direction: "out", status: "sent" }), // neuer: ersetzt
    event(12n, { itemId: 9n }), // neue Nachricht
    event(12n, { itemId: 8n, customerId: 2n }), // anderer Kunde
    event(13n, { itemId: 9n }), // Wiederholung derselben Nachricht
  ];
  const merged = conversationItems(pages, events, 1n, 5n, true);
  expect(ids(merged)).toEqual([5n, 7n, 9n]);
  expect(merged[1]?.status).toBe("sent");

  // spätere Seite mit älterem Stand als ein bekanntes Ereignis-Update ändert nichts am Ergebnis
  expect(conversationItems(withPage(pages, [item({ itemId: 7n, status: "sending" })], 10n), events, 1n, 5n, true)[1]?.status).toBe("sent");
});

test("Verlauf: Ereignis vor der ältesten geladenen Seite bleibt weg, solange ältere Seiten fehlen", () => {
  const pages = withPage(new Map(), [item({ itemId: 50n })], 5n);
  const events = [event(6n, { itemId: 40n })];
  expect(ids(conversationItems(pages, events, 1n, 50n, true))).toEqual([50n]);
  expect(ids(conversationItems(pages, events, 1n, 50n, false))).toEqual([40n, 50n]);
});

test("Kundenliste: neuere Ereignisse überlagern die Seite, leere Akte entfernt, Default zuerst", () => {
  const c = (init: MessageInitShape<typeof CustomerSummarySchema>) =>
    create(CustomerSummarySchema, { kind: "customer", customerNo: `DF-C-${init.customerId}`, ...init });
  const page = [c({ customerId: 1n, kind: "internal" }), c({ customerId: 2n, lastMs: 100n }), c({ customerId: 3n, lastMs: 50n })];
  const upd = (cursor: bigint, init: MessageInitShape<typeof CustomerSummarySchema>) => ({
    cursor,
    committedMs: 0,
    value: create(CustomerUpdatedSchema, { customer: create(CustomerSummarySchema, init) }),
  });
  const merged = mergeCustomers(page, 4n, [
    upd(3n, { customerId: 2n, kind: "customer", lastMs: 1n, unread: 9 }), // in der Seite enthalten
    upd(5n, { customerId: 3n, kind: "customer", lastMs: 200n, unread: 1 }),
    upd(6n, { customerId: 4n, kind: "customer", lastMs: 150n }), // Erstkontakt
    upd(7n, { customerId: 2n }), // nur die ID: Akte entfernt
  ]);
  expect(merged.map((m) => m.customerId)).toEqual([1n, 3n, 4n]);
  expect(merged[1]?.unread).toBe(1);
});

test("Gelesen: Gesamt bis zum neuesten Eingang; Kanal nur bis vor den ersten ungelesenen anderen Kanal", () => {
  const items = [
    item({ itemId: 1n, read: true }),
    item({ itemId: 2n }),
    item({ itemId: 3n, direction: "out", read: true }),
    item({ itemId: 4n, platform: "instagram" }),
    item({ itemId: 5n }),
  ];
  expect(markReadTarget(items, null)).toBe(5n);
  expect(markReadTarget(items, "telegram")).toBe(2n);
  expect(markReadTarget(items, "instagram")).toBe(0n); // ungelesener Telegram-Eingang davor
  expect(markReadTarget([item({ itemId: 1n, read: true })], null)).toBe(0n);
});

test("Antwortziel: genau eine Konversation des Kanals, sonst ein Grund", () => {
  const ident = (init: MessageInitShape<typeof ChannelIdentitySchema>) => create(ChannelIdentitySchema, init);
  const tg = ident({ identityId: 1n, platform: "telegram", conversationId: 7n, revision: 3n });
  expect(replyTarget([tg], "telegram")).toBe(tg);
  expect(replyTarget([tg], "instagram")).toBe("Kanal nicht verknüpft");
  expect(replyTarget([ident({ identityId: 2n, platform: "instagram" })], "instagram")).toBe("Noch keine Konversation in diesem Kanal");
  expect(typeof replyTarget([tg, ident({ identityId: 1n, platform: "telegram", conversationId: 8n })], "telegram")).toBe("string");
});

test("Abfrage: je Schlüssel einmal; Wechsel während einer Anfrage ergeben genau eine Folgeanfrage", async () => {
  const runs: string[] = [];
  const finish: (() => void)[] = [];
  const q = new VersionedQuery(
    (key) =>
      new Promise<void>((resolve) => {
        runs.push(key);
        finish.push(resolve);
      }),
  );
  q.request("a");
  q.request("a");
  q.request("b");
  q.request("c");
  expect(runs).toEqual(["a"]);
  finish.shift()!();
  await new Promise((r) => setTimeout(r, 0));
  expect(runs).toEqual(["a", "c"]);
  finish.shift()!();
  await new Promise((r) => setTimeout(r, 0));
  q.request("c");
  expect(runs).toEqual(["a", "c"]);
});
