import {afterEach,expect,test,vi} from "vitest";
import {readRestartContext} from "./restart-client";

const plan="00000000-0000-4000-8000-000000000001";
const task="00000000-0000-4000-8000-000000000002";
const value={schemaVersion:4,planId:plan,taskId:task,sourceConditionsRevision:1,sourceStartingBottle:null,input:{schemaVersion:4,phase:"research",sourceText:null,intent:{mode:"similar",origin_query:"格蘭菲迪 12 年",explore_feature:null,contrast:null,smoke_comparison:false}}};
afterEach(()=>vi.unstubAllGlobals());

test("restart context reads no-store and validates plan, task and confirmed research phase",async()=>{
  const fetcher=vi.fn(async()=>Response.json(value));
  vi.stubGlobal("fetch",fetcher);
  expect(await readRestartContext(plan,task,"fixture-token")).toEqual(value);
  expect(fetcher.mock.calls[0]).toMatchObject([`/api/v1/plans/${plan}/tasks/${task}/restart-context`,{cache:"no-store",headers:{Authorization:"Bearer fixture-token"}}]);
  for(const changed of [{...value,planId:task},{...value,taskId:plan},{...value,input:{schemaVersion:4,phase:"research",sourceText:null}},{...value,input:{...value.input,phase:"proposal",sourceText:"重新解讀"}}]){
    fetcher.mockResolvedValueOnce(Response.json(changed));
    await expect(readRestartContext(plan,task,"fixture-token")).rejects.toThrow("INVALID_RESPONSE");
  }
});
