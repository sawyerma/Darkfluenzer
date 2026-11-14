import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import {
  CommandRequestSchema,
  CommandResponseSchema,
  CommandStatus,
} from "./generated/darkfluenzer/v1/commands_pb";
import { MediaPageSchema, type MediaPage } from "./generated/darkfluenzer/v1/media_pb";
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

/** Galerie-Seite (neueste zuerst) auf konkreten Aufruf: Protobuf-GET, kein Polling. */
export async function fetchMediaPage(before: bigint, limit: number): Promise<MediaPage> {
  const url = `/api/v1/media-page?before=${before}&limit=${limit}`;
  let resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (resp.status === 401) {
    await refreshSession();
    resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  }
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return fromBinary(MediaPageSchema, new Uint8Array(await resp.arrayBuffer()));
}
