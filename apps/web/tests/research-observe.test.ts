import { expect, test, vi } from "vitest";
import { observeTask } from "../src/features/research/observe";
import type { ResearchState } from "../src/features/research/state";
import { ObservationError } from "../src/features/research/transport";

const initial: ResearchState = {
  taskId:"00000000-0000-4000-8000-000000000001", threadId:"00000000-0000-4000-8000-000000000002",
  conditionsRevision:1, connection:0, view:null, connected:false,
};
const runId = "00000000-0000-4000-8000-000000000003";
function stream(version: number) {
  return new Response([
    {type:"RUN_STARTED", threadId:initial.threadId, runId},
    {type:"STATE_SNAPSHOT", snapshot:{schemaVersion:1, taskId:initial.taskId, threadId:initial.threadId, conditionsRevision:1, viewVersion:version, status:"researching", stage:"合成重連測試", question:null, reportId:null, error:null, observedAt:"2026-09-28T00:00:00Z"}},
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join(""), {headers:{"Content-Type":"text/event-stream"}});
}

test("EOF reconnects read-only observation with a fresh token and preserves task state", async () => {
  const abort = new AbortController();
  const states: ResearchState[] = [];
  const token = vi.fn().mockResolvedValueOnce("first").mockResolvedValueOnce("second");
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(stream(1)).mockResolvedValueOnce(stream(2));
  const sleep = vi.fn(async () => {if (fetch.mock.calls.length === 2) abort.abort();});
  await observeTask({initial, runId, token, fetch, sleep, random:()=>0.5, signal:abort.signal, onState:state=>states.push(state)});
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(token).toHaveBeenCalledTimes(2);
  for (const [index, call] of fetch.mock.calls.entries()) {
    const request = call[0] as Request;
    expect(new URL(request.url).pathname).toBe("/agent/observe");
    expect(request.headers.get("authorization")).toBe(`Bearer ${index ? "second" : "first"}`);
    expect(await request.json()).toEqual({taskId:initial.taskId, runId, conditionsRevision:1});
  }
  expect(states.filter(state=>state.view?.viewVersion===2).length).toBeGreaterThan(0);
  expect(states.at(-1)?.view?.status).toBe("researching");
  expect(states.at(-1)?.connected).toBe(false);
  expect(sleep.mock.calls.length).toBe(2);
});

test("temporary network failure retries with jitter but revoked access stops", async () => {
  const abort = new AbortController();
  const fetch = vi.fn<typeof globalThis.fetch>()
    .mockRejectedValueOnce(new TypeError("network"))
    .mockResolvedValueOnce(new Response('data: {"type":"RUN_ERROR","code":"OBSERVATION_ACCESS_LOST","message":"unavailable"}\n\n', {headers:{"Content-Type":"text/event-stream"}}));
  const sleep = vi.fn(async (_milliseconds: number, _signal: AbortSignal) => undefined);
  await expect(observeTask({initial, runId, token:async()=>"token", fetch, sleep, random:()=>0.5, signal:abort.signal, onState:()=>{}})).rejects.toMatchObject(new ObservationError("OBSERVATION_ACCESS_LOST", false));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(sleep).toHaveBeenCalledTimes(1);
  expect(sleep.mock.calls[0][0]).toBeGreaterThanOrEqual(1000);
});

test("logout while getting a token neither opens a connection nor restores private state", async () => {
  const abort = new AbortController();
  const fetch = vi.fn<typeof globalThis.fetch>();
  const onState = vi.fn();
  await observeTask({initial, runId, token:async()=>{abort.abort(); return "late";}, fetch, sleep:async()=>{}, random:()=>0, signal:abort.signal, onState});
  expect(fetch).not.toHaveBeenCalled();
  expect(onState).not.toHaveBeenCalled();
});

test("saved terminal snapshot stops reconnecting without inferring success from EOF", async () => {
  const response = stream(1);
  const text = (await response.text()).replace('"status":"researching"', '"status":"completed"').replace('"reportId":null', `"reportId":"${runId}"`);
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(new Response(text, {headers:{"Content-Type":"text/event-stream"}}));
  const sleep = vi.fn(async () => {throw new Error("terminal task must not reconnect");});
  const states: ResearchState[] = [];
  await observeTask({initial, runId, token:async()=>"token", fetch, sleep, random:()=>0, signal:new AbortController().signal, onState:state=>states.push(state)});
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(sleep).not.toHaveBeenCalled();
  expect(states.at(-1)?.view?.status).toBe("completed");
});

test("durable input wait ends this turn's observation instead of reconnecting forever", async () => {
  const waiting = {schemaVersion:1, taskId:initial.taskId, threadId:initial.threadId,
    conditionsRevision:1, viewVersion:3, status:"needs_input", stage:"等待版本補充",
    question:{id:runId,prompt:"哪個版本？",waitingVersion:1,expiresAt:"2026-10-06T00:00:00Z",
      choices:[{id:runId,label:"15 年"}]}, reportId:null,error:null,observedAt:"2026-09-29T00:00:00Z"};
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(
    `data: ${JSON.stringify({type:"RUN_STARTED",threadId:initial.threadId,runId})}\n\n` +
    `data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot:waiting})}\n\n`,
    {headers:{"Content-Type":"text/event-stream"}},
  ));
  const sleep = vi.fn(async () => {throw new Error("input wait must not reconnect");});
  const states: ResearchState[] = [];
  await observeTask({initial,runId,token:async()=>"token",fetch,sleep,random:()=>0,signal:new AbortController().signal,onState:state=>states.push(state)});
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(sleep).not.toHaveBeenCalled();
  expect(states.at(-1)?.view?.status).toBe("needs_input");
});
