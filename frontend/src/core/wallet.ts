import { fromBinary } from "@bufbuild/protobuf";
import { useEffect, useMemo, useRef, useState } from "react";
import { Topic } from "./generated/darkfluenzer/v1/stream_pb";
import { PaymentPageSchema, type Payment, type PaymentPage } from "./generated/darkfluenzer/v1/wallet_pb";
import { protectedGet } from "./media";
import { useConnection } from "./realtime";
import { useEventTopic } from "./state";

// Zahlungseingänge (FRONT F7.8): Seiten je Filter per Protobuf-GET auf Aufruf, neue und geänderte
// Eingänge als EVENT payment.updated – kein Polling. Je payment_id genau ein Eintrag.

const PAGE_SIZE = 50;

export type PaymentFilter = "all" | "open" | "confirmed" | "unassigned";
export type PaymentsStatus = "ready" | "loading" | "offline";

// Dieselbe Regel wie das Backend (store.payment_page): Push-Einträge landen im richtigen Filter
// und verlassen ihn, sobald sich ihr Status ändert.
const MATCH: Record<PaymentFilter, (status: string) => boolean> = {
  all: () => true,
  open: (s) => s === "detected",
  confirmed: (s) => s === "confirmed" || s === "assigned",
  unassigned: (s) => s === "unassigned",
};

async function fetchPaymentPage(filter: PaymentFilter, before: bigint): Promise<PaymentPage> {
  const resp = await protectedGet(`/api/v1/payment-page?before=${before}&limit=${PAGE_SIZE}&filter=${filter}`);
  return fromBinary(PaymentPageSchema, new Uint8Array(await resp.arrayBuffer()));
}

interface Pages {
  filter: PaymentFilter;
  items: Payment[];
  more: boolean;
  loaded: boolean;
}

const empty = (filter: PaymentFilter): Pages => ({ filter, items: [], more: false, loaded: false });

/** Eingänge des Filters, neueste zuerst: erste Seite beim Aufruf, ältere nur auf Wunsch. */
export function usePayments(filter: PaymentFilter) {
  const log = useEventTopic(Topic.PAYMENT_UPDATED);
  const connection = useConnection();
  const [pages, setPages] = useState<Pages>(() => empty(filter));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const wanted = useRef(filter);
  wanted.current = filter;
  const current = pages.filter === filter ? pages : empty(filter);

  const items = useMemo(() => {
    const byId = new Map<bigint, Payment>();
    for (const p of current.items) byId.set(p.paymentId, p);
    for (const e of log?.items ?? []) if (e.value.payment) byId.set(e.value.payment.paymentId, e.value.payment);
    // Ältere Push-Einträge erst mit ihrer Seite zeigen: sonst entstünde eine Lücke vor „Ältere laden“.
    const oldest = current.more ? current.items.at(-1)?.paymentId : undefined;
    return [...byId.values()]
      .filter((p) => MATCH[filter](p.status) && (oldest === undefined || p.paymentId >= oldest))
      .sort((a, b) => (b.paymentId > a.paymentId ? 1 : b.paymentId < a.paymentId ? -1 : 0));
  }, [current, log, filter]);

  async function load(f: PaymentFilter, before: bigint) {
    setLoading(true);
    setError("");
    try {
      const page = await fetchPaymentPage(f, before);
      if (wanted.current !== f) return; // Filter inzwischen gewechselt
      setPages((p) => ({
        filter: f,
        items: [...(before && p.filter === f ? p.items : []), ...page.items],
        more: page.more,
        loaded: true,
      }));
    } catch (e) {
      if (wanted.current === f) setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (connection.status === "OPEN" && !current.loaded) void load(filter, 0n);
  }, [connection.status, filter, current.loaded]);

  useEffect(() => {
    // Nach Reconnect fehlen Ereignisse: Seite neu laden statt veraltete Einträge zeigen
    if (log?.gap) setPages((p) => empty(p.filter));
  }, [log?.gap]);

  const status: PaymentsStatus = current.loaded ? "ready" : connection.status === "OPEN" ? "loading" : "offline";
  return {
    items,
    more: current.more,
    loading,
    error,
    status,
    live: connection.status === "OPEN" && !!log?.live,
    loadOlder: () => load(filter, current.items.at(-1)?.paymentId ?? 0n),
  };
}
