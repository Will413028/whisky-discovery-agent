import {afterEach,expect,test,vi} from "vitest";
import {startResearchV4,type ResearchInputV4} from "./client";
import type {TaskView} from "./state";

const id="00000000-0000-4000-8000-000000000001";
const runId="00000000-0000-4000-8000-000000000002";
const plan={id,conditionsRevision:2};
const snapshot:TaskView={schemaVersion:1,taskId:id,threadId:id,conditionsRevision:2,viewVersion:2,status:"queued",stage:"已受理",question:null,reportId:null,error:null,observedAt:"2026-10-01T00:00:00Z",activeRunId:runId};
afterEach(()=>vi.unstubAllGlobals());

const inputs = [
  {schemaVersion:4,phase:"proposal",sourceText:"我喜歡甜點",intent:{mode:"style_options",smoke_comparison:false,origin_query:null,explore_feature:null,contrast:null}},
  {schemaVersion:4,phase:"research",sourceText:null,intent:{mode:"similar",origin_query:"合成起點12年",smoke_comparison:false,explore_feature:null,contrast:null}},
] satisfies ResearchInputV4[];
test.each(inputs)("V4 starts carry the exact immutable input inside the existing AG-UI transport",async input=>{
  const fetch=vi.fn(async(_url,init)=>{
    expect(init.headers).toMatchObject({Authorization:"Bearer fixture"});
    expect(JSON.parse(init.body)).toMatchObject({threadId:id,runId,messages:[],state:{},tools:[],context:[],forwardedProps:{type:"start_v4",key:"stable-key",planId:id,conditionsRevision:2,input}});
    if(input.phase==="research") expect(JSON.parse(init.body).forwardedProps.sourceTaskId).toBe(runId);
    return new Response(`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot})}\n\n`,{headers:{"Content-Type":"text/event-stream"}});
  });
  vi.stubGlobal("fetch",fetch);
  expect(await startResearchV4("fixture",plan,"stable-key",id,runId,input,...(input.phase==="research" ? [runId] as [string] : []))).toEqual(snapshot);
  expect(fetch.mock.calls[0][0]).toBe("/agent");
});
