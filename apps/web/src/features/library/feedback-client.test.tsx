import {afterEach,expect,test,vi} from "vitest";
import {FeedbackRejected,listBottleFeedback,readBottleFeedback,saveBottleFeedback,type SaveBottleFeedback} from "./feedback-client";
const id="00000000-0000-4000-8000-000000000001";
const other="00000000-0000-4000-8000-000000000002";
const command:SaveBottleFeedback={schemaVersion:1,key:"stable-feedback",bottleVersionId:id,expectedRevision:0,wantToExplore:true,tasting:"not_tasted",tastingReason:""};
const value={schemaVersion:1,id,bottleVersionId:id,revision:1,wantToExplore:true,tasting:"not_tasted",tastingReason:"",createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
afterEach(()=>vi.unstubAllGlobals());
test("feedback write binds the accepted revision and tasting to the immutable private command",async()=>{
  const fetch=vi.fn(async()=>Response.json(value));vi.stubGlobal("fetch",fetch);
  expect(await saveBottleFeedback(command,"fixture")).toEqual(value);
  expect(fetch).toHaveBeenCalledWith("/api/v1/library/feedback",expect.objectContaining({method:"POST",cache:"no-store",headers:{Authorization:"Bearer fixture","Content-Type":"application/json"},body:JSON.stringify(command)}));
});
test("reopening reads explicit own feedback instead of inferring from a saved selection",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(value)));
  expect(await readBottleFeedback(id,"fixture")).toEqual(value);
});
test("a missing feedback record is an explicit empty state",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code:"NOT_FOUND"},{status:404})));
  expect(await readBottleFeedback(id,"fixture")).toBeNull();
});
test.each([{...value,bottleVersionId:other},{...value,revision:2},{...value,tasting:"liked"}])("a mismatched write receipt cannot become successful feedback",async invalid=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(invalid)));
  await expect(saveBottleFeedback(command,"fixture")).rejects.toThrow("INVALID_RESPONSE");
});
test("a confirmed revision rejection provides a recovery code instead of an unknown write",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code:"REVISION_CONFLICT"},{status:409})));
  try {await saveBottleFeedback(command,"fixture");throw new Error("EXPECTED_REJECTION");}
  catch(error) {expect(error).toBeInstanceOf(FeedbackRejected);expect(error).toMatchObject({code:"REVISION_CONFLICT",status:409});}
});
test("saved favorites and tasting restore through bounded private pages",async()=>{
  const page={schemaVersion:1,items:[value],nextCursor:"opaque"};
  const fetch=vi.fn(async()=>Response.json(page));vi.stubGlobal("fetch",fetch);
  expect(await listBottleFeedback("fixture","opaque")).toEqual(page);
  expect(fetch).toHaveBeenCalledWith("/api/v1/library/feedback?cursor=opaque",expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer fixture"}}));
});
