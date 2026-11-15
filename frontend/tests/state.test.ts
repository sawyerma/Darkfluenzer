import { create, toBinary } from "@bufbuild/protobuf";
import { expect, test, vi } from "vitest";
import {
  ComfyState,
  ComfyInstancesSchema,
  JobCompletedSchema,
  JobResult,
} from "../src/core/generated/darkfluenzer/v1/comfy_pb";
import {
  CatchupCompleteSchema,
  EventSchema,
  StateFullSchema,
  Topic,
} from "../src/core/generated/darkfluenzer/v1/stream_pb";

async function freshState() {
  vi.resetModules();
  return await import("../src/core/state");
}

function comfyFrame(generation: bigint, seq: bigint, state: ComfyState) {
  const payload = toBinary(ComfyInstancesSchema, create(ComfyInstancesSchema, { instances: [{ name: "media", state }] }));
  return create(StateFullSchema, { topic: Topic.COMFY_INSTANCES, generation, seq, payload });
}

function jobEvent(cursor: bigint) {
  const payload = toBinary(
    JobCompletedSchema,
    create(JobCompletedSchema, { jobId: cursor, workflow: "lustify_sdxl_t2i", result: JobResult.DONE }),
  );
  return create(EventSchema, { topic: Topic.JOB_COMPLETED, cursor, committedUnixMs: 1n, payload });
}

const catchup = (through: bigint, gap: boolean) =>
  create(CatchupCompleteSchema, { topic: Topic.JOB_COMPLETED, through, gap });

test("STATE: älterer Stand verworfen, Trennung veraltet, Snapshot nach Reconnect bestätigt", async () => {
  const s = await freshState();
  expect(s.applyState(comfyFrame(1n, 2n, ComfyState.READY))).toBe(true);
  expect(s.applyState(comfyFrame(1n, 1n, ComfyState.STOPPED))).toBe(false);
  expect(s.stateOf(Topic.COMFY_INSTANCES)?.value.instances[0]?.state).toBe(ComfyState.READY);

  s.markStale();
  expect(s.stateOf(Topic.COMFY_INSTANCES)?.staleSince).not.toBeNull();
  expect(s.applyState(comfyFrame(1n, 2n, ComfyState.READY))).toBe(true); // gleicher Stand
  expect(s.stateOf(Topic.COMFY_INSTANCES)?.staleSince).toBeNull();

  // Neuer Backend-Lauf: höhere Generation gilt trotz kleinerer seq
  expect(s.applyState(comfyFrame(2n, 1n, ComfyState.STOPPED))).toBe(true);
  expect(s.stateOf(Topic.COMFY_INSTANCES)?.value.instances[0]?.state).toBe(ComfyState.STOPPED);
});

test("EVENT: Duplikate verworfen, Lücke sichtbar, ersetztes Journal setzt zurück", async () => {
  const s = await freshState();
  expect(s.applyEvent(jobEvent(3n))).toBe(true);
  expect(s.applyEvent(jobEvent(7n))).toBe(true);
  expect(s.applyEvent(jobEvent(7n))).toBe(false); // Wiederholung nach Reconnect
  expect(s.applyEvent(jobEvent(5n))).toBe(false); // älter als der angewendete Cursor
  s.catchupComplete(catchup(9n, false));
  let log = s.eventLogOf(Topic.JOB_COMPLETED);
  expect(log?.items.map((i) => i.cursor)).toEqual([3n, 7n]);
  expect(log?.live).toBe(true);
  expect(log?.gap).toBe(false);

  s.catchupComplete(catchup(9n, true));
  expect(s.eventLogOf(Topic.JOB_COMPLETED)?.gap).toBe(true);

  s.catchupComplete(catchup(2n, false)); // Journal-Kopf unter eigenem Cursor: ersetzt
  log = s.eventLogOf(Topic.JOB_COMPLETED);
  expect(log?.items).toEqual([]);
  expect(log?.lastCursor).toBe(0n);
  expect(log?.gap).toBe(true);
});
