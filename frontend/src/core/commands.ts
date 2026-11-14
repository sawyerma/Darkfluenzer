import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { useState } from "react";
import {
  CommandRequestSchema,
  CommandResponseSchema,
  CommandStatus,
} from "./generated/darkfluenzer/v1/commands_pb";
import { csrfToken, refreshSession } from "./realtime";

// Benutzeraktionen als Protobuf-POST mit eindeutiger request_id (PHASENPLAN_FRONT_V1 F3).
// "Angenommen" heißt nicht "ausgeführt": das Ergebnis kommt als STATE/EVENT.

type Command = MessageInitShape<typeof CommandRequestSchema>["command"];

export interface CommandResult {
  accepted: boolean;
  detail: string;
}

export async function sendCommand(command: Command): Promise<CommandResult> {
  const body = toBinary(CommandRequestSchema, create(CommandRequestSchema, { requestId: crypto.randomUUID(), command }));
  let resp = await post(body, csrfToken());
  if (resp.status === 401 || resp.status === 403) {
    // Sitzung abgelaufen (z. B. Backend neu gestartet): einmal erneuern, gleiche request_id.
    resp = await post(body, await refreshSession());
  }
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  const answer = fromBinary(CommandResponseSchema, new Uint8Array(await resp.arrayBuffer()));
  return { accepted: answer.status === CommandStatus.ACCEPTED, detail: answer.detail };
}

function post(body: Uint8Array, csrf: string): Promise<Response> {
  return fetch("/api/v1/command", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/x-protobuf", "X-CSRF-Token": csrf },
    body,
  });
}

/** Befehl mit Wartezustand und Rückmeldung (Ablehnungsgrund oder Fehler) für eine Komponente. */
export function useCommand() {
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  async function run(command: Command, accepted = ""): Promise<boolean> {
    setPending(true);
    setNotice("");
    try {
      const result = await sendCommand(command);
      setNotice(result.accepted ? accepted : result.detail);
      return result.accepted;
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setPending(false);
    }
  }
  return { pending, notice, run };
}
