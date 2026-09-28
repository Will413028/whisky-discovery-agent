import type { components } from "../../../../../contracts/api";
import { disconnected, snapshot, type ResearchState } from "./state";
import { ObservationError, readEvents } from "./transport";

export type ObserveOptions = {
  initial: ResearchState;
  runId: string;
  token: () => Promise<string>;
  onState: (state: ResearchState) => void;
  signal: AbortSignal;
  fetch: typeof fetch;
  sleep: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  random: () => number;
};

export async function observeTask(options: ObserveOptions): Promise<void> {
  const fetchResponse = options.fetch;
  let state = options.initial;
  let failures = 0;
  while (!options.signal.aborted) {
    state = {...state, connection:state.connection + 1, connected:false};
    const connection = state.connection;
    try {
      const token = await options.token();
      options.signal.throwIfAborted();
      const body: components["schemas"]["ObserveInput"] = {
        taskId:state.taskId, runId:options.runId, conditionsRevision:state.conditionsRevision,
      };
      await readEvents(signal => fetchResponse(new Request(new URL("/agent/observe", location.origin), {
        method:"POST", headers:{Authorization:`Bearer ${token}`, "Content-Type":"application/json"},
        body:JSON.stringify(body), signal,
      })), event => {
        if (event.type === "RUN_ERROR") {
          throw new ObservationError(event.code ?? "OBSERVATION_UNAVAILABLE", event.code === "OBSERVATION_UNAVAILABLE");
        }
        if (event.type === "RUN_STARTED") {
          if (event.runId !== options.runId || event.threadId !== state.threadId) throw new ObservationError("INVALID_STREAM", false);
          state = {...state, connected:true};
        }
        if (event.type === "STATE_SNAPSHOT") {
          state = snapshot(state, event.snapshot, connection);
          failures = 0;
        }
        options.onState(state);
      }, options.signal);
    } catch (error) {
      if (options.signal.aborted) return;
      if (!(error instanceof ObservationError) || !error.retryable) throw error;
      failures = Math.min(failures + 1, 5);
    } finally {
      if (!options.signal.aborted) {
        state = disconnected(state, connection);
        options.onState(state);
      }
    }
    if (state.view && ["needs_input", "completed", "failed", "cancelled", "superseded"].includes(state.view.status)) return;
    try {
      await options.sleep(Math.min(30_000, 1000 * 2 ** failures) + options.random() * 1000, options.signal);
    } catch (error) {
      if (options.signal.aborted) return;
      throw error;
    }
  }
}
