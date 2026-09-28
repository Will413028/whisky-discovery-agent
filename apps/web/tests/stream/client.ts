import { readEvents } from "../../src/features/research/transport";
import { snapshot, disconnected, type ResearchState } from "../../src/features/research/state";

let state: ResearchState = {
  taskId:"00000000-0000-4000-8000-000000000001", threadId:"00000000-0000-4000-8000-000000000002",
  conditionsRevision:1, connection:1, view:null, connected:true,
};
const times: number[] = [];
const output = document.querySelector("output")!;
void readEvents(() => fetch("/agent/observe", {method:"POST"}), (event) => {
  if (event.type === "STATE_SNAPSHOT") {
    state = snapshot(state, event.snapshot, 1);
    times.push(performance.now());
  }
}).then(() => {
  state = disconnected(state, 1);
  output.textContent = JSON.stringify({status:state.view?.status, connected:state.connected, times});
}).catch(() => {output.textContent = "fixture failed";});
