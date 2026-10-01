import {afterEach, expect, test, vi} from "vitest";
import {listHistory} from "./history-client";

const id="00000000-0000-4000-8000-000000000001";
const task={schemaVersion:1,taskId:id,threadId:id,conditionsRevision:1,viewVersion:1,status:"completed",stage:"完成",question:null,reportId:id,error:null,observedAt:"2026-09-30T00:00:00Z",activeRunId:null};
const item={task,createdAt:"2026-09-29T00:00:00Z"};
afterEach(()=>vi.unstubAllGlobals());

test("history validates task status payloads and creation time, retaining private transport and opaque cursor",async()=>{
  const signal=new AbortController().signal;
  const fetch=vi.fn(async(_url,init)=>{
    expect(init).toMatchObject({headers:{Authorization:"Bearer fixture-token"},cache:"no-store",signal});
    return Response.json({items:[item],nextCursor:null});
  });
  vi.stubGlobal("fetch",fetch);
  expect(await listHistory(id,"fixture-token","opaque=cursor",signal)).toEqual({items:[item],nextCursor:null});
  expect(fetch.mock.calls[0][0]).toBe(`/api/v1/plans/${id}/tasks?cursor=opaque%3Dcursor`);
});

test.each([
  {...item,createdAt:"not-a-date"},
  {...item,task:{...task,reportId:null}},
])("invalid historical projections never become report links",async value=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({items:[value],nextCursor:null})));
  await expect(listHistory(id,"fixture-token",null)).rejects.toThrow("INVALID_RESPONSE");
});
