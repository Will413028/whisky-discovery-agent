import { EventSchemas, type AGUIEvent } from "@ag-ui/core";
import { EventSourceParserStream } from "eventsource-parser/stream";

export class ObservationError extends Error {
  constructor(public readonly code: string, public readonly retryable: boolean) { super(code); }
}

export async function readEvents(fetchResponse: (signal?: AbortSignal) => Promise<Response>, onEvent: (event: AGUIEvent) => void | Promise<void>, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  let response: Response;
  try { response = await fetchResponse(signal); }
  catch {
    signal?.throwIfAborted();
    throw new ObservationError("OBSERVATION_UNAVAILABLE", true);
  }
  if (signal?.aborted) {
    await response.body?.cancel();
    signal.throwIfAborted();
  }
  if (!response.ok || !response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
    await response.body?.cancel();
    throw new ObservationError(response.status === 401 ? "AUTH_REQUIRED" : "OBSERVATION_UNAVAILABLE", response.status === 429 || response.status >= 500);
  }
  const upstream = response.body.getReader();
  const source = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const {done, value} = await upstream.read();
        if (done) { controller.close(); upstream.releaseLock(); }
        else controller.enqueue(value);
      } catch {
        controller.error(new ObservationError("OBSERVATION_UNAVAILABLE", true));
        upstream.releaseLock();
      }
    },
    async cancel(reason) {
      await upstream.cancel(reason).catch(() => undefined);
      upstream.releaseLock();
    },
  });
  const reader = source
    .pipeThrough(new TransformStream<Uint8Array, BufferSource>({transform(chunk, controller) {
      if (chunk.byteLength > 1_048_576) throw new ObservationError("INVALID_STREAM", false);
      controller.enqueue(new Uint8Array(chunk).buffer);
    }}))
    .pipeThrough(new TextDecoderStream("utf-8", {fatal:true}))
    .pipeThrough(new EventSourceParserStream({maxBufferSize:65_536, onError:"terminate"}))
    .getReader();
  const abort = () => { void reader.cancel(signal?.reason).catch(() => undefined); };
  signal?.addEventListener("abort", abort, {once:true});
  try {
    while (true) {
      const {done, value} = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      await onEvent(EventSchemas.parse(JSON.parse(value.data)));
    }
  } catch (error) {
    signal?.throwIfAborted();
    if (error instanceof ObservationError) throw error;
    throw new ObservationError("INVALID_STREAM", false);
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
