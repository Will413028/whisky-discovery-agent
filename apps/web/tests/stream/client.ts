import { readEvents } from "../../src/features/research/transport";
import { snapshot, disconnected, type ResearchState } from "../../src/features/research/state";
import { observeTask } from "../../src/features/research/observe";

let state: ResearchState = {
  taskId:"00000000-0000-4000-8000-000000000001", threadId:"00000000-0000-4000-8000-000000000002",
  conditionsRevision:1, connection:1, view:null, connected:true,
};
const times: number[] = [];
const output = document.querySelector("output")!;
if (new URL(location.href).searchParams.has("reconnect")) {
  const abort = new AbortController();
  let tokens = 0;
  let stopped = false;
  state = {...state, connection:0, connected:false};
  const render = () => {output.textContent = JSON.stringify({status:state.view?.status, version:state.view?.viewVersion, connection:state.connection, tokens, stopped});};
  void observeTask({
    initial:state, runId:"00000000-0000-4000-8000-000000000004",
    token:async()=>`synthetic-token-${++tokens}`, signal:abort.signal, fetch,
    random:Math.random,
    sleep:(milliseconds, signal)=>new Promise((resolve, reject)=>{
      if (signal.aborted) {reject(signal.reason); return;}
      const onAbort = () => {clearTimeout(timer); reject(signal.reason);};
      const timer = setTimeout(()=>{signal.removeEventListener("abort", onAbort); resolve();}, milliseconds);
      signal.addEventListener("abort", onAbort, {once:true});
    }),
    onState:next=>{
      state = next;
      if (next.connection === 2 && !next.connected) abort.abort();
      render();
    },
  }).then(()=>{stopped = true; render();}).catch(error=>{output.textContent = `fixture failed: ${error.code ?? "unknown"}`;});
} else {
void readEvents(() => fetch("/agent/observe", {method:"POST"}), (event) => {
  if (event.type === "STATE_SNAPSHOT") {
    state = snapshot(state, event.snapshot, 1);
    times.push(performance.now());
  }
}).then(() => {
  state = disconnected(state, 1);
  output.textContent = JSON.stringify({status:state.view?.status, connected:state.connected, times});
}).catch(() => {output.textContent = "fixture failed";});
}
