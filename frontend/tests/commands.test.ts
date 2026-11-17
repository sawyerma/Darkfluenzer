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

test("4xx vor dem Journal ist endgültig: ein Versuch, kein „Verbindung unterbrochen“, settle endet (FABLE-009)", async () => {
  const posted: number[] = [];
  let reject = 413;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/session") {
        return new Response(null, { status: 204, headers: { "X-CSRF-Token": "t", "X-Command-Wait-S": "0.02" } });
      }
      if (url === "/api/v1/command") {
        posted.push((init!.body as Uint8Array).length);
        return new Response(reject === 413 ? "Befehl zu groß" : "Ungültiger CommandRequest", { status: reject });
      }
      if (url.startsWith("/api/v1/command/")) return new Response("", { status: 404 });
      throw new Error(`unerwartet ${url}`);
    }),
  );
  await refreshSession();
  const command = { case: "pauseQueue", value: { paused: true } } as const;
  const sent = await sendCommand(command);
  expect(posted.length).toBe(1); // kein erneutes Hochladen des ganzen Körpers
  expect(sent.accepted).toBe(false);
  expect(sent.unknown).toBe(false);
  expect(sent.detail).toBe("Abgewiesen (413): Befehl zu groß");

  // Quittung fehlt, Status 404, erneutes Senden wird abgewiesen -> Endzustand statt Schleife
  reject = 400;
  const receipt = await settle(command, 0n, sent.requestId, () => {});
  expect(receipt.status).toBe(CommandStatus.REJECTED);
  expect(receipt.detail).toBe("Abgewiesen (400): Ungültiger CommandRequest");
  expect(posted.length).toBe(2);
});

test("5xx bleibt „Ergebnis unbekannt“: gleiche request_id, danach Statusabfrage (FABLE-009)", async () => {
  const posted: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/session") return new Response(null, { status: 204, headers: { "X-CSRF-Token": "t" } });
      if (url === "/api/v1/command") {
        posted.push(fromBinary(CommandRequestSchema, init!.body as Uint8Array).requestId);
        return new Response("", { status: 500 });
      }
      throw new Error(`unerwartet ${url}`);
    }),
  );
  const sent = await sendCommand({ case: "pauseQueue", value: { paused: true } });
  expect(sent.unknown).toBe(true);
  expect(sent.detail.startsWith("Verbindung unterbrochen")).toBe(true);
  expect(new Set(posted)).toEqual(new Set([sent.requestId]));
});
