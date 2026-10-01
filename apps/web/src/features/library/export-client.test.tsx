import {afterEach,expect,test,vi} from "vitest";
import {readAccountExport} from "./export-client";
const owner="00000000-0000-4000-8000-000000000001";
const data={libraryHistory:[],conditionChanges:[],identities:[],plans:[],tasks:[],reports:[],questions:[],preferenceProposals:[],sourceObservations:[],researchInputs:[],agentTurns:[],comparisons:[],conclusions:[],feedback:[],preferences:[],reportCandidates:[],reportClaims:[],reportCitations:[],reportPrices:[],reportSourceObservations:[],catalogItems:[],catalogEvidence:[],catalogPrices:[]};
const value={schemaVersion:1,ownerId:owner,generation:1,exportedAt:"2026-10-01T00:00:00Z",data};
function exported(body:unknown){const json=JSON.stringify(body);return new Response(json,{headers:{"content-type":"application/json","x-export-owner":owner,"x-export-generation":"1","x-export-schema":"1","x-export-bytes":String(new TextEncoder().encode(json).length)}});}
afterEach(()=>vi.unstubAllGlobals());
test("download validates the complete export and binds it to the authenticated actor",async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(exported(value));vi.stubGlobal("fetch",fetch);
  expect(JSON.parse(await (await readAccountExport("fixture")).text())).toEqual(value);
  expect(fetch).toHaveBeenLastCalledWith("/api/v1/library/export",expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer fixture"}}));
});
test.each([{...value,ownerId:"00000000-0000-4000-8000-000000000002"},{...value,data:{...data,reports:undefined}}])("foreign or incomplete files cannot be downloaded",async invalid=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(exported(invalid)));
  await expect(readAccountExport("fixture")).rejects.toThrow("INVALID_RESPONSE");
});
test("large complete files remain native blobs instead of hitting the small JSON limit",async()=>{
  const large={...value,data:{...data,researchInputs:[{task_id:owner,input:{synthetic:"x".repeat(9*1024*1024)},source_task_id:null}]}};
  const response=exported(large);const size=Number(response.headers.get("x-export-bytes"));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(response));
  const file=await readAccountExport("fixture");
  expect(file.size).toBe(size);expect(file.size).toBeGreaterThan(8*1024*1024);
});
test.each(["x-export-owner","x-export-schema","x-export-generation","x-export-bytes"])("invalid %s metadata cannot trigger a download",async header=>{
  const response=exported(value);response.headers.set(header,"invalid");
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(response));
  await expect(readAccountExport("fixture")).rejects.toThrow("INVALID_RESPONSE");
});
test("a truncated body never becomes a completed file",async()=>{
  const response=exported(value);response.headers.set("x-export-bytes",String(Number(response.headers.get("x-export-bytes"))+1));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(response));
  await expect(readAccountExport("fixture")).rejects.toThrow("INVALID_RESPONSE");
});
