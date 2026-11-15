import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { useState } from "react";
import {
  CommandRequestSchema,
  CommandResponseSchema,
  CommandStatus,
  type CommandReceipt,
} from "./generated/darkfluenzer/v1/commands_pb";
import { Topic } from "./generated/darkfluenzer/v1/stream_pb";
import { csrfToken, refreshSession } from "./realtime";
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
};

export interface CommandResult {
  accepted: boolean;
  detail: string;
  entity: string;
  requestId: string;
}

/** Sendet einen Befehl; ``expectedVersion`` = gesehene Domain-Version (CAS, z. B. Workflows.version). */
export async function sendCommand(command: Command, expectedVersion = 0n): Promise<CommandResult> {
  const requestId = crypto.randomUUID();
  const body = toBinary(CommandRequestSchema, create(CommandRequestSchema, { requestId, expectedVersion, command }));
  let failure = "";
  for (let attempt = 0; attempt < SEND_ATTEMPTS; attempt++) {
    try {
      let resp = await post(body, attempt === 0 ? csrfToken() : await refreshSession());
      if (resp.status === 401 || resp.status === 403) resp = await post(body, await refreshSession());
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
      const answer = fromBinary(CommandResponseSchema, new Uint8Array(await resp.arrayBuffer()));
      return { accepted: answer.status === CommandStatus.ACCEPTED, detail: answer.detail, entity: answer.entity, requestId };
    } catch (e) {
      failure = e instanceof Error ? e.message : String(e);
    }
  }
  return { accepted: false, detail: `Verbindung unterbrochen – Ergebnis unbekannt (${failure})`, entity: "", requestId };
}

function post(body: Uint8Array, csrf: string): Promise<Response> {
  return fetch("/api/v1/command", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/x-protobuf", "X-CSRF-Token": csrf },
    body,
  });
}

/** Wartet auf die terminale Receipt dieser request_id (auch wenn sie vor der HTTP-Antwort kam). */
export function terminalReceipt(requestId: string): Promise<CommandReceipt> {
  const known = eventLogOf(Topic.COMMAND_RECEIPT)?.items.find(
    (e) => e.value.requestId === requestId && TERMINAL.has(e.value.status),
  );
  if (known) return Promise.resolve(known.value);
  return new Promise((resolve) => {
    const off = onReceipt((r) => {
      if (r.requestId === requestId && TERMINAL.has(r.status)) {
        off();
        resolve(r);
      }
    });
  });
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
        if (result.detail.startsWith("Verbindung unterbrochen")) {
          const late = await terminalReceipt(result.requestId);
          setNotice(late.status === CommandStatus.COMPLETED ? (opts.done ?? "") : `${OUTCOME[late.status] ?? ""} ${late.detail}`.trim());
          return late.status === CommandStatus.COMPLETED ? { ...result, accepted: true, entity: late.entity } : null;
        }
        return null;
      }
      if (opts.acceptedOnly) {
        setNotice(opts.done ?? "");
        return result;
      }
      const receipt = await terminalReceipt(result.requestId);
      if (receipt.status !== CommandStatus.COMPLETED) {
        setNotice(`${OUTCOME[receipt.status] ?? ""}${receipt.detail ? `: ${receipt.detail}` : ""}`);
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
