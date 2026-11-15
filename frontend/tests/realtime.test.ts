import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ComfyInstancesSchema, JobCompletedSchema } from "../src/core/generated/darkfluenzer/v1/comfy_pb";
import {
  ClientMessageSchema,
  ServerMessageSchema,
  Topic,
  TopicClass,
  WelcomeStatus,
  type ClientMessage,
} from "../src/core/generated/darkfluenzer/v1/stream_pb";

// Testdoppel für Browser-APIs (fetch, WebSocket, location, sessionStorage); der Code darunter
// ist der echte Verbindungs- und Zustandscode.
class FakeSocket {
  static all: FakeSocket[] = [];
  binaryType = "";
  sent: ClientMessage[] = [];
  onopen?: () => void;
  onmessage?: (ev: { data: ArrayBuffer }) => void;
  onclose?: (ev: { code: number; reason: string }) => void;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  send(data: Uint8Array) {
    this.sent.push(fromBinary(ClientMessageSchema, data));
  }
  close() {
    this.onclose?.({ code: 1006, reason: "" });
  }
  server(msg: MessageInitShape<typeof ServerMessageSchema>) {
    const bytes = toBinary(ServerMessageSchema, create(ServerMessageSchema, msg));
    this.onmessage?.({ data: bytes.slice().buffer });
  }
}

const reload = vi.fn();
const storage = new Map<string, string>();

beforeEach(() => {
  FakeSocket.all = [];
  storage.clear();
  reload.mockReset();
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("location", { protocol: "http:", host: "127.0.0.1:8190", reload });
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => storage.set(k, v),
    removeItem: (k: string) => storage.delete(k),
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204, headers: { "X-CSRF-Token": "t" } })),
  );
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Wartet, bis der n-te Socket existiert (Sitzungsabruf ist asynchron), und öffnet ihn. */
async function connected(n: number): Promise<FakeSocket> {
  await vi.waitFor(() => expect(FakeSocket.all.length).toBe(n));
  const socket = FakeSocket.all[n - 1]!;
  socket.onopen?.();
  return socket;
}

const TOPICS = [
  { topic: Topic.COMFY_INSTANCES, topicClass: TopicClass.STATE, payloadType: ComfyInstancesSchema.typeName },
  { topic: Topic.JOB_COMPLETED, topicClass: TopicClass.EVENT, payloadType: JobCompletedSchema.typeName },
];

test("Handshake, Abonnements, Abbruch -> veraltet -> Reconnect mit Resume-Cursor", async () => {
  const rt = await import("../src/core/realtime");
  rt.connect();
  const first = await connected(1);
  const hello = first.sent[0]!.msg;
  expect(hello.case === "hello" && hello.value.schemaId).toBe(__DF_SCHEMA_ID__);

  first.server({ msg: { case: "welcome", value: { status: WelcomeStatus.ACCEPTED, heartbeatIntervalMs: 15000, topics: TOPICS } } });
  expect(rt.connectionInfo().status).toBe("OPEN");
  expect(first.sent.slice(1).map((m) => m.msg.case === "subscribe" && m.msg.value.topic)).toEqual([
    Topic.COMFY_INSTANCES,
    Topic.JOB_COMPLETED,
  ]);
  const payload = toBinary(JobCompletedSchema, create(JobCompletedSchema, { jobId: 1n }));
  first.server({ msg: { case: "event", value: { topic: Topic.JOB_COMPLETED, cursor: 42n, payload } } });
  first.server({ msg: { case: "catchupComplete", value: { topic: Topic.JOB_COMPLETED, through: 42n } } });

  first.close(); // Netzabbruch
  expect(rt.connectionInfo().status).toBe("STALE");
  await vi.advanceTimersByTimeAsync(1_000); // Backoff mit Jitter
  const second = await connected(2);
  second.server({ msg: { case: "welcome", value: { status: WelcomeStatus.ACCEPTED, heartbeatIntervalMs: 15000, topics: TOPICS } } });
  const resume = second.sent.find((m) => m.msg.case === "subscribe" && m.msg.value.topic === Topic.JOB_COMPLETED);
  expect(resume?.msg.case === "subscribe" && resume.msg.value.afterCursor).toBe(42n);
  expect(rt.connectionInfo().status).toBe("OPEN");
});

test("Schema-Konflikt: genau einmal neu laden, danach blockiert statt Schleife", async () => {
  let rt = await import("../src/core/realtime");
  rt.connect();
  let socket = await connected(1);
  socket.server({ msg: { case: "welcome", value: { status: WelcomeStatus.REJECTED_SCHEMA, schemaId: "neu" } } });
  expect(reload).toHaveBeenCalledTimes(1);

  vi.resetModules(); // die neu geladene Seite
  rt = await import("../src/core/realtime");
  rt.connect();
  socket = await connected(2);
  socket.server({ msg: { case: "welcome", value: { status: WelcomeStatus.REJECTED_SCHEMA, schemaId: "neu" } } });
  expect(reload).toHaveBeenCalledTimes(1);
  expect(rt.connectionInfo().status).toBe("BLOCKED");
});
