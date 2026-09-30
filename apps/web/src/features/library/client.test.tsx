import {afterEach,expect,test,vi} from "vitest";
import {saveConclusion,listConclusions,readConclusionContext,ConclusionRejected} from "./client";

const id="00000000-0000-4000-8000-000000000001";
const other="00000000-0000-4000-8000-000000000002";
const command={schemaVersion:1 as const,key:"stable",planId:id,reportId:id,expectedConditionsRevision:1,selectedVersionId:null,reason:"這次沒有適合的",tradeoff:""};
const value={schemaVersion:1,id,planId:id,taskId:id,reportId:id,conditionsRevision:1,conditions:{schema_version:1,entry:"beginner",goal:"探索",budget_twd:null,preferences:[]},catalogReleaseId:null,evaluatedOn:"2026-10-01",revision:1,outcome:"no_suitable",selectedVersionId:null,selectedBottleName:null,alternativeVersionIds:[],reason:command.reason,tradeoff:"",createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
afterEach(()=>vi.unstubAllGlobals());
test("save preserves the immutable command and private transport",async()=>{
  const fetch=vi.fn(async()=>Response.json(value));vi.stubGlobal("fetch",fetch);
  expect(await saveConclusion(command,"fixture")).toEqual(value);
  expect(fetch).toHaveBeenCalledWith("/api/v1/library/conclusions",expect.objectContaining({method:"POST",cache:"no-store",headers:{Authorization:"Bearer fixture","Content-Type":"application/json"},body:JSON.stringify(command)}));
});
test.each([{...value,planId:other},{...value,reportId:other},{...value,conditionsRevision:2},{...value,outcome:"selected"},{...value,selectedVersionId:id,selectedBottleName:"合成候選",outcome:"selected",alternativeVersionIds:[id]}])("invalid or mismatched saved results are rejected",async invalid=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(invalid)));
  await expect(saveConclusion(command,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});
test("a changed plan revision is a conflict rather than a successful save",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code:"REVISION_CONFLICT"},{status:409})));
  await expect(saveConclusion(command,"fixture")).rejects.toThrow("REVISION_CONFLICT");
});
test.each(["IDEMPOTENCY_CONFLICT","IDENTITY_CHANGED"])("an acknowledged %s keeps its own rejection code",async code=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code},{status:409})));
  try {await saveConclusion(command,"fixture");throw new Error("EXPECTED_REJECTION");}
  catch(error) {expect(error).toBeInstanceOf(ConclusionRejected);expect(error).toMatchObject({code,status:409});}
});
test("reopening a plan reads its saved historical conclusions privately",async()=>{
  const page={schemaVersion:1,planId:id,items:[value],nextCursor:null};
  const fetch=vi.fn(async()=>Response.json(page));vi.stubGlobal("fetch",fetch);
  expect(await listConclusions(id,"fixture")).toEqual(page);
  expect(fetch).toHaveBeenCalledWith(`/api/v1/library/conclusions?planId=${id}`,expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer fixture"}}));
});
test.each([{schemaVersion:1,planId:other,items:[value],nextCursor:null},{schemaVersion:1,planId:id,items:[{...value,planId:other}],nextCursor:null}])("foreign plan pages cannot enter state",async page=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(page)));
  await expect(listConclusions(id,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});
test("conclusion context identifies the server-owned parent and current plan revision",async()=>{
  const context={schemaVersion:1,planId:id,taskId:id,reportId:id,conditionsRevision:1,currentConditionsRevision:2};
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(context)));
  expect(await readConclusionContext(id,id,1,"fixture")).toEqual(context);
});
test("a context from another task cannot authorize a save",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({schemaVersion:1,planId:id,taskId:other,reportId:id,conditionsRevision:1,currentConditionsRevision:1})));
  await expect(readConclusionContext(id,id,1,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});
