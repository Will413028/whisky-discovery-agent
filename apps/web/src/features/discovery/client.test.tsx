import {afterEach, expect, test, vi} from "vitest";
import {listPlans, patchPlan, readControl, readPlan, RequestRejected} from "./client";

const id = "00000000-0000-4000-8000-000000000001";
const commandId = "00000000-0000-4000-8000-000000000002";
const conditions = {schema_version:1 as const, entry:"beginner" as const, goal:"果香", budget_twd:"1000", preferences:[], starting_bottle:null};
const plan = {id, conditionsRevision:1, conditions};
const command = {id:commandId, targetId:id, kind:"plan.change_conditions" as const, status:"pending" as const, result:null};
afterEach(() => {vi.unstubAllGlobals();});

test("plan pages preserve opaque cursors and validate their nested saved conditions", async () => {
  const fetch = vi.fn(async (_url:RequestInfo | URL) => Response.json({items:[plan],nextCursor:null}));
  vi.stubGlobal("fetch", fetch);
  expect(await listPlans("fixture-token","opaque=cursor")).toEqual({items:[plan],nextCursor:null});
  expect(fetch.mock.calls[0][0]).toBe("/api/v1/plans?cursor=opaque%3Dcursor");
});

test("plan reads validate the saved conditions and retain auth, no-store, and abort", async () => {
  const controller = new AbortController();
  const fetch = vi.fn(async (_url, init) => {
    expect(init.headers.Authorization).toBe("Bearer fixture-token");
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBe(controller.signal);
    return Response.json(plan);
  });
  vi.stubGlobal("fetch", fetch);
  expect(await readPlan(id, "fixture-token", controller.signal)).toEqual(plan);
  expect(fetch).toHaveBeenCalledWith(`/api/v1/plans/${id}`, expect.anything());
});

test("partial edits send the same immutable revision and base on every retry", async () => {
  const bodies: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
    bodies.push(init.body);
    return Response.json(command, {status:202});
  }));
  const body = {key:commandId, expectedRevision:1, baseConditions:conditions, patch:{budget_twd:"900", upsert_preferences:[], remove_preferences:[]}};
  expect(await patchPlan(id, "fixture-token", body)).toEqual(command);
  expect(await patchPlan(id, "fixture-token", body)).toEqual(command);
  expect(bodies).toEqual([JSON.stringify(body), JSON.stringify(body)]);
});

test("a command read accepts the durable completion for the exact command only", async () => {
  const completed = {...command, status:"completed", result:{conditionsRevision:"2"}};
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(completed)));
  expect(await readControl(commandId, "fixture-token")).toEqual(completed);
});

test("invalid saved conditions cannot be treated as a usable plan", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({...plan, conditions:{...conditions, budget_twd:"not-money"}})));
  await expect(readPlan(id, "fixture-token")).rejects.toThrow("INVALID_RESPONSE");
});

test("canonical fractional budget text remains a readable saved budget", async () => {
  const scientific = {...plan, conditions:{...conditions, budget_twd:"1000.25"}};
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(scientific)));
  expect(await readPlan(id, "fixture-token")).toEqual(scientific);
});

test.each([409,422] as const)("HTTP %s is a definite rejection, rather than an unknown transport result", async status => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("private upstream detail",{status})));
  const body = {key:commandId,expectedRevision:1,baseConditions:conditions,patch:{budget_twd:"900",upsert_preferences:[],remove_preferences:[]}};
  await expect(patchPlan(id,"fixture-token",body)).rejects.toBeInstanceOf(RequestRejected);
  await expect(patchPlan(id,"fixture-token",body)).rejects.toMatchObject({status});
});
