import {afterEach, expect, test, vi} from "vitest";
import {readComparison} from "./comparison-client";

const id="00000000-0000-4000-8000-000000000001";
const other="00000000-0000-4000-8000-000000000002";
const value={schemaVersion:4,reportId:id,taskId:id,conditionsRevision:1,catalogReleaseId:null,evaluatedOn:"2026-09-30",comparison:{schemaVersion:4,intent:{mode:"style_options",origin_query:null,explore_feature:null,contrast:null,smoke_comparison:false},candidates:[],unresolved:[],unlistedName:null},items:[]};
afterEach(()=>vi.unstubAllGlobals());

test("comparison reads preserve private transport and validate the requested report and task",async()=>{
  const signal=new AbortController().signal;
  const fetch=vi.fn(async(_url,init)=>{
    expect(init).toMatchObject({headers:{Authorization:"Bearer fixture"},cache:"no-store",signal});
    return Response.json(value);
  });
  vi.stubGlobal("fetch",fetch);
  expect(await readComparison(id,id,"fixture",signal)).toEqual(value);
  expect(fetch.mock.calls[0][0]).toBe(`/api/v1/reports/${id}/comparison`);
});

test("legacy reports have no comparison artifact",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(null,{status:404})));
  expect(await readComparison(id,id,"fixture")).toBeNull();
});

test.each([
  {...value,reportId:other},
  {...value,taskId:other},
  {...value,schemaVersion:1},
  {...value,evaluatedOn:"not-a-date"},
  {...value,comparison:{...value.comparison,candidates:[{}]}},
])("invalid comparisons cannot enter UI state",async invalid=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(invalid)));
  await expect(readComparison(id,id,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});

test("authentication failure is distinct from a legacy missing artifact",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(null,{status:401})));
  await expect(readComparison(id,id,"fixture")).rejects.toThrow("AUTH_REQUIRED");
});
