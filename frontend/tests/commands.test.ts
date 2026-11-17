import { create, fromBinary, toBinary } from "@bufbuild/protobuf";
import { afterEach, expect, test, vi } from "vitest";
import {
  CommandReceiptSchema,
  CommandRequestSchema,
  CommandResponseSchema,
  CommandStatus,
} from "../src/core/generated/darkfluenzer/v1/commands_pb";
import { sendCommand, settle } from "../src/core/commands";
import { refreshSession } from "../src/core/realtime";

// Testdoppel nur für fetch; Warten, Statusabfrage und erneutes Senden sind der echte Code.
afterEach(() => vi.unstubAllGlobals());

test("ohne Quittung: Statusabfrage, bei 404 derselbe Befehl mit derselben request_id (BUG-024)", async () => {
  const posted: string[] = [];
  let statusCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/session") {
        return new Response(null, { status: 204, headers: { "X-CSRF-Token": "t", "X-Command-Wait-S": "0.02" } });
      }
      if (url === "/api/v1/command") {
        const req = fromBinary(CommandRequestSchema, init!.body as Uint8Array);
        posted.push(req.requestId);
        const answer = create(CommandResponseSchema, { requestId: req.requestId, status: CommandStatus.ACCEPTED });
        return new Response(toBinary(CommandResponseSchema, answer), { status: 200 });
      }
      if (url.startsWith("/api/v1/command/")) {
        statusCalls++;
        if (statusCalls === 1) return new Response("", { status: 404 }); // nie angekommen?
        const receipt = create(CommandReceiptSchema, { requestId: posted[0], status: CommandStatus.COMPLETED, command: "pause_queue" });
        return new Response(toBinary(CommandReceiptSchema, receipt), { status: 200 });
      }
      throw new Error(`unerwartet ${url}`);
    }),
  );
  await refreshSession(); // Wartezeit aus der Sitzungsantwort (server.command_wait_s)
  const command = { case: "pauseQueue", value: { paused: true } } as const;
  const sent = await sendCommand(command);
  let unknown = 0;
  const receipt = await settle(command, 0n, sent.requestId, () => unknown++);
  expect(receipt.status).toBe(CommandStatus.COMPLETED);
  expect(posted).toEqual([sent.requestId, sent.requestId]); // erneut gesendet, dieselbe request_id
  expect(unknown).toBe(2); // zweimal „Ergebnis unbekannt, Status wird geprüft“
});
