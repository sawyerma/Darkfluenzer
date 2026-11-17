import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { useState } from "react";
import {
  CommandReceiptSchema,
  CommandRequestSchema,
  CommandResponseSchema,
  CommandStatus,
  type CommandReceipt,
} from "./generated/darkfluenzer/v1/commands_pb";
import { Topic } from "./generated/darkfluenzer/v1/stream_pb";
import { commandWaitMs, csrfToken, refreshSession } from "./realtime";
import { eventLogOf, onReceipt } from "./state";

// Benutzeraktionen als Protobuf-POST mit eindeutiger request_id (PHASENPLAN_FRONT_V1 DF-PUSH C).
// ACCEPTED heißt nur "angenommen": erst die persistierte Receipt (EVENT command.receipt) belegt
// das Ergebnis. Bei Netzfehlern wird DIESELBE request_id erneut gesendet (das Backend führt sie
// höchstens einmal aus) – nie eine neue Aktion.

type Command = MessageInitShape<typeof CommandRequestSchema>["command"];

const SEND_ATTEMPTS = 3;
const TERMINAL = new Set([
  CommandStatus.COMPLETED,
  CommandStatus.FAILED,
  CommandStatus.UNKNOWN,
  CommandStatus.CANCELLED,
  CommandStatus.REJECTED,
]);
const OUTCOME: Partial<Record<CommandStatus, string>> = {
  [CommandStatus.FAILED]: "Fehlgeschlagen",
  [CommandStatus.UNKNOWN]: "Ergebnis unbekannt",
  [CommandStatus.CANCELLED]: "Abgebrochen",
  [CommandStatus.REJECTED]: "Abgewiesen",
};

export interface CommandResult {
  accepted: boolean;
  detail: string;
  entity: string;
  requestId: string;
  /** Ergebnis unbekannt (Netz weg oder Serverfehler 5xx): Status abfragen, nie neu ausführen. */
  unknown: boolean;
}

/** Sendet einen Befehl; ``expectedVersion`` = gesehene Domain-Version (CAS, z. B. Workflows.version). */
export async function sendCommand(command: Command, expectedVersion = 0n, requestId: string = crypto.randomUUID()): Promise<CommandResult> {
  const body = toBinary(CommandRequestSchema, create(CommandRequestSchema, { requestId, expectedVersion, command }));
  let failure = "";
  for (let attempt = 0; attempt < SEND_ATTEMPTS; attempt++) {
    try {
      let resp = await post(body, attempt === 0 ? csrfToken() : await refreshSession());
      if (resp.status === 401 || resp.status === 403) resp = await post(body, await refreshSession());
      if (resp.status >= 400 && resp.status < 500) {
        // Vor dem Befehlsjournal abgewiesen (400 ungültig, 413 zu groß, 415 Typ, 403 Herkunft):
        // endgültig, kein erneutes Hochladen und kein „Ergebnis unbekannt“ (FABLE-009).
        const why = (await resp.text()).trim();
        return { accepted: false, detail: `Abgewiesen (${resp.status})${why ? `: ${why}` : ""}`, entity: "", requestId, unknown: false };
      }
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`); // 5xx: Ergebnis unbekannt
      const answer = fromBinary(CommandResponseSchema, new Uint8Array(await resp.arrayBuffer()));
      return { accepted: answer.status === CommandStatus.ACCEPTED, detail: answer.detail, entity: answer.entity, requestId, unknown: false };
    } catch (e) {
      failure = e instanceof Error ? e.message : String(e);
    }
  }
  return { accepted: false, detail: `Verbindung unterbrochen – Ergebnis unbekannt (${failure})`, entity: "", requestId, unknown: true };
}

function post(body: Uint8Array, csrf: string): Promise<Response> {
  return fetch("/api/v1/command", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/x-protobuf", "X-CSRF-Token": csrf },
    body,
  });
}

/** Wartet höchstens ``timeoutMs`` auf die terminale Receipt dieser request_id (auch wenn sie vor
 *  der HTTP-Antwort kam); ``null`` = Zeit abgelaufen. */
export function terminalReceipt(requestId: string, timeoutMs: number): Promise<CommandReceipt | null> {
  const known = eventLogOf(Topic.COMMAND_RECEIPT)?.items.find(
    (e) => e.value.requestId === requestId && TERMINAL.has(e.value.status),
  );
  if (known) return Promise.resolve(known.value);
  return new Promise((resolve) => {
    const off = onReceipt((r) => {
      if (r.requestId === requestId && TERMINAL.has(r.status)) {
        off();
        clearTimeout(timer);
        resolve(r);
      }
    });
    const timer = setTimeout(() => {
      off();
      resolve(null);
    }, timeoutMs);
  });
}

type StatusAnswer = { kind: "receipt"; receipt: CommandReceipt } | { kind: "missing" } | { kind: "error" };

/** Befehlsstatus beim Backend (SP2 Schritt 11): Quittung, „nicht bekannt“ (404) oder Fehler. */
export async function commandStatus(requestId: string): Promise<StatusAnswer> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const resp = await fetch(`/api/v1/command/${encodeURIComponent(requestId)}`, { credentials: "same-origin", cache: "no-store" });
      if (resp.status === 401) {
        await refreshSession();
        continue;
      }
      if (resp.status === 404) return { kind: "missing" };
      if (!resp.ok) return { kind: "error" };
      return { kind: "receipt", receipt: fromBinary(CommandReceiptSchema, new Uint8Array(await resp.arrayBuffer())) };
    } catch {
      return { kind: "error" };
    }
  }
  return { kind: "error" };
}

export const UNKNOWN_NOTICE = "Ergebnis unbekannt, Status wird geprüft";

/** Bis zum Endzustand warten (BUG-024): Zeit abgelaufen oder Verbindung weg -> Status abfragen;
 *  „in Bearbeitung“ -> weiter warten; 404 -> DENSELBEN Befehl mit derselben request_id erneut
 *  senden (das Backend führt ihn höchstens einmal aus), nie eine neue request_id. Wird der erneut
 *  gesendete Befehl abgewiesen, ist das der Endzustand (FABLE-009). */
export async function settle(command: Command, version: bigint, requestId: string, onUnknown: () => void): Promise<CommandReceipt> {
  for (;;) {
    const receipt = await terminalReceipt(requestId, commandWaitMs());
    if (receipt) return receipt;
    onUnknown();
    const answer = await commandStatus(requestId);
    if (answer.kind === "receipt" && TERMINAL.has(answer.receipt.status)) return answer.receipt;
    if (answer.kind === "missing") {
      const again = await sendCommand(command, version, requestId);
      if (!again.accepted && !again.unknown) {
        return create(CommandReceiptSchema, { requestId, status: CommandStatus.REJECTED, detail: again.detail });
      }
    }
  }
}

export interface RunOptions {
  /** Gesehene Domain-Version (CAS). */
  version?: bigint;
  /** Meldung nach belegtem Erfolg. */
  done?: string;
  /** Nur auf die Annahme warten (lang laufende Aufträge, deren Fortschritt die Warteschlange zeigt). */
  acceptedOnly?: boolean;
}

/** Befehl mit Wartezustand und Rückmeldung für eine Komponente: wartet auf den belegten Zustand
 *  (terminale Receipt) und liefert true nur bei COMPLETED bzw. – mit ``acceptedOnly`` – bei Annahme. */
export function useCommand() {
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  async function run(command: Command, opts: RunOptions = {}): Promise<CommandResult | null> {
    setPending(true);
    setNotice("");
    try {
      const result = await sendCommand(command, opts.version ?? 0n);
      if (!result.accepted) {
        setNotice(result.detail);
        if (result.unknown) {
          const late = await settle(command, opts.version ?? 0n, result.requestId, () => setNotice(UNKNOWN_NOTICE));
          setNotice(late.status === CommandStatus.COMPLETED ? (opts.done ?? "") : `${OUTCOME[late.status] ?? ""} ${late.detail}`.trim());
          return late.status === CommandStatus.COMPLETED ? { ...result, accepted: true, entity: late.entity } : null;
        }
        return null;
      }
      if (opts.acceptedOnly) {
        setNotice(opts.done ?? "");
        return result;
      }
      const receipt = await settle(command, opts.version ?? 0n, result.requestId, () => setNotice(UNKNOWN_NOTICE));
      if (receipt.status !== CommandStatus.COMPLETED) {
        setNotice([OUTCOME[receipt.status], receipt.detail].filter(Boolean).join(": "));
        return null;
      }
      setNotice(opts.done ?? "");
      return result;
    } finally {
      setPending(false);
    }
  }
  return { pending, notice, run };
}
