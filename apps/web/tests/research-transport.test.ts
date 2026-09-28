// @vitest-environment node
import { expect, test, vi } from "vitest";
import { readEvents } from "../src/features/research/transport";

test("delivers an event before the upstream closes, across UTF-8 and SSE chunks", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({start(value) {controller = value;}});
  const onEvent = vi.fn();
  const reading = readEvents(async () => new Response(stream, {headers:{"Content-Type":"text/event-stream"}}), onEvent);
  const event = {type:"STATE_SNAPSHOT", snapshot:{label:"等待補充"}};
  const data = new TextEncoder().encode(`: heartbeat\r\n\r\ndata: ${JSON.stringify(event)}\r\n\r\n`);
  try {
    for (const byte of data) controller.enqueue(new Uint8Array([byte]));
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith(event), {timeout:500});
  } finally { controller.close(); await reading; }
});

test("abort cancels a pending upstream read", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = vi.fn();
  const stream = new ReadableStream<Uint8Array>({start(value) {controller = value;}, cancel:cancelled});
  const abort = new AbortController();
  const reading = readEvents(async () => new Response(stream, {headers:{"Content-Type":"text/event-stream"}}), vi.fn(), abort.signal);
  const outcome = reading.catch((error: unknown) => error);
  await vi.waitFor(() => expect(stream.locked).toBe(true));
  abort.abort();
  try { await vi.waitFor(() => expect(cancelled).toHaveBeenCalled(), {timeout:500}); }
  finally { if (!cancelled.mock.calls.length) controller.close(); await outcome; }
  expect(await outcome).toMatchObject({name:"AbortError"});
});

test.each([
  'data: {bad json}\n\n',
  'data: {"type":"UNKNOWN_EVENT"}\n\n',
  'data: ' + 'x'.repeat(65_537),
])("rejects malformed or oversized stream data", async (body) => {
  const consume = vi.fn();
  await expect(readEvents(async () => new Response(body, {headers:{"Content-Type":"text/event-stream"}}), consume)).rejects.toMatchObject({code:"INVALID_STREAM"});
  expect(consume).not.toHaveBeenCalled();
});

test("an incomplete frame at EOF never becomes an event", async () => {
  const consume = vi.fn();
  await readEvents(async () => new Response('data: {"type":"STATE_SNAPSHOT","snapshot":{}}', {headers:{"Content-Type":"text/event-stream"}}), consume);
  expect(consume).not.toHaveBeenCalled();
});

test("initial network failure has a safe retryable error", async () => {
  await expect(readEvents(async () => {throw new TypeError("private upstream URL");}, vi.fn()))
    .rejects.toMatchObject({code:"OBSERVATION_UNAVAILABLE", message:"OBSERVATION_UNAVAILABLE", retryable:true});
});

test("network failure after a snapshot remains retryable", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({start(value) {controller = value;}});
  const consume = vi.fn();
  const outcome = readEvents(async () => new Response(stream, {headers:{"Content-Type":"text/event-stream"}}), consume).catch((error:unknown) => error);
  controller.enqueue(new TextEncoder().encode('data: {"type":"STATE_SNAPSHOT","snapshot":{}}\n\n'));
  await vi.waitFor(() => expect(consume).toHaveBeenCalledTimes(1));
  controller.error(new TypeError("network lost"));
  expect(await outcome).toMatchObject({code:"OBSERVATION_UNAVAILABLE", retryable:true});
});

test("expired auth is explicit and never exposes the response body", async () => {
  await expect(readEvents(async () => new Response("private details", {status:401}), vi.fn())).rejects.toMatchObject({code:"AUTH_REQUIRED", retryable:false});
});

test("a slow consumer is awaited before the next event", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {release = resolve;});
  const consume = vi.fn(async () => {await gate;});
  const event = 'data: {"type":"STATE_SNAPSHOT","snapshot":{}}\n\n';
  const reading = readEvents(async () => new Response(event + event, {headers:{"Content-Type":"text/event-stream"}}), consume);
  await vi.waitFor(() => expect(consume).toHaveBeenCalled());
  const callsBeforeRelease = consume.mock.calls.length;
  release();
  await reading;
  expect(callsBeforeRelease).toBe(1);
  expect(consume).toHaveBeenCalledTimes(2);
});
