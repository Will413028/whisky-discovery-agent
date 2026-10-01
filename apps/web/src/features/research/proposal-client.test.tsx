import {afterEach,expect,test,vi} from "vitest";
import {readPreferenceProposal} from "./proposal-client";
import type {TaskView} from "./state";

const id="00000000-0000-4000-8000-000000000001";
const questionId="00000000-0000-4000-8000-000000000002";
const task:TaskView={schemaVersion:1,taskId:id,threadId:id,conditionsRevision:2,viewVersion:3,status:"needs_input",stage:"等待偏好確認",question:{id:questionId,prompt:"確認探索方向",choices:[{id,label:"使用"}],waitingVersion:1,expiresAt:"2026-10-08T00:00:00Z"},reportId:null,error:null,observedAt:"2026-10-01T00:00:00Z",activeRunId:null};
const proposal={summary:"甜香只是線索",intent:{mode:"style_options",smoke_comparison:false},preferences:[{description:"甜香",intent:"prefer",source_quote:"喜歡甜點",source_kind:"food_clue",certainty:"inferred",strength:"soft"}],budget:null};
const view={schemaVersion:4,taskId:id,planId:id,questionId,conditionsRevision:2,waitingVersion:1,sourceText:"我喜歡甜點",proposal};
afterEach(()=>vi.unstubAllGlobals());

test("proposal reads retain private transport and its exact active question",async()=>{
  const signal=new AbortController().signal;
  const fetch=vi.fn(async(_url,init)=>{
    expect(init).toMatchObject({headers:{Authorization:"Bearer fixture"},cache:"no-store",signal});
    return Response.json(view);
  });
  vi.stubGlobal("fetch",fetch);
  expect(await readPreferenceProposal(task,"fixture",signal)).toEqual(view);
  expect(fetch.mock.calls[0][0]).toBe(`/api/v1/tasks/${id}/preference-proposal`);
});

test.each([
  {...view,taskId:questionId},
  {...view,questionId:id},
  {...view,conditionsRevision:3},
  {...view,waitingVersion:2},
  {...view,schemaVersion:1},
  {...view,proposal:{...proposal,preferences:[{}]}},
])("mismatched or malformed drafts never enter UI state",async invalid=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(invalid)));
  await expect(readPreferenceProposal(task,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});

test("a non-proposal or closed question has no preference draft",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(null,{status:404})));
  expect(await readPreferenceProposal(task,"fixture")).toBeNull();
});

test("a task without a waiting question never requests private draft content",async()=>{
  const fetch=vi.fn();
  vi.stubGlobal("fetch",fetch);
  expect(await readPreferenceProposal({...task,status:"cancelled",question:null},"fixture")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

test("expired authentication remains an error",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(null,{status:401})));
  await expect(readPreferenceProposal(task,"fixture")).rejects.toThrow("AUTH_REQUIRED");
});
