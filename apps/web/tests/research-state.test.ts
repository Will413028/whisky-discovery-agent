import { expect, test } from "vitest";
import { disconnected, snapshot, type ResearchState } from "../src/features/research/state";

const initial: ResearchState = {
  taskId:"00000000-0000-4000-8000-000000000001", threadId:"00000000-0000-4000-8000-000000000002",
  conditionsRevision:1, connection:1, view:null, connected:true,
};
const view = {
  schemaVersion:1, taskId:initial.taskId, threadId:initial.threadId, conditionsRevision:1, viewVersion:1,
  status:"researching", stage:"查核來源", question:null, reportId:null, error:null, observedAt:"2026-09-28T00:00:00Z",
};

test("a current snapshot is accepted and EOF only marks the connection lost", () => {
  const state = snapshot(initial, view, 1);
  expect(state.view).toEqual(view);
  const ended = disconnected(state, 1);
  expect(ended.connected).toBe(false);
  expect(ended.view?.status).toBe("researching");
});

test.each([
  {taskId:"00000000-0000-4000-8000-000000000003"},
  {threadId:"00000000-0000-4000-8000-000000000003"},
  {conditionsRevision:2}, {viewVersion:1},
])("rejects foreign, old, and duplicate snapshots: %j", (changes) => {
  const current = snapshot(initial, {...view, viewVersion:2}, 1);
  expect(snapshot(current, {...view, viewVersion:3, ...changes}, 1)).toBe(current);
  expect(snapshot(current, {...view, viewVersion:2}, 1)).toBe(current);
});

test("old connections cannot overwrite or disconnect the current subscription", () => {
  const current = {...snapshot(initial, view, 1), connection:2};
  expect(snapshot(current, {...view, viewVersion:2}, 1)).toBe(current);
  expect(disconnected(current, 1)).toBe(current);
});

test("malformed snapshots and missing terminal payloads never update the screen", () => {
  for (const changes of [{status:"needs_input"}, {status:"completed"}, {status:"failed"}, {schemaVersion:2}, {viewVersion:0}]) {
    expect(snapshot(initial, {...view, ...changes}, 1)).toBe(initial);
  }
});
