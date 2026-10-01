import {afterEach,expect,test,vi} from "vitest";
import {readAccountExport} from "./export-client";
const owner="00000000-0000-4000-8000-000000000001";
const data={libraryHistory:[],conditionChanges:[],identities:[],plans:[],tasks:[],reports:[],questions:[],preferenceProposals:[],sourceObservations:[],researchInputs:[],agentTurns:[],comparisons:[],conclusions:[],feedback:[],preferences:[],reportCandidates:[],reportClaims:[],reportCitations:[],reportPrices:[],reportSourceObservations:[],catalogItems:[],catalogEvidence:[],catalogPrices:[]};
const value={schemaVersion:1,ownerId:owner,generation:1,exportedAt:"2026-10-01T00:00:00Z",data};
afterEach(()=>vi.unstubAllGlobals());
test("download validates the complete export and binds it to the authenticated actor",async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(Response.json(value));vi.stubGlobal("fetch",fetch);
  expect(await readAccountExport("fixture")).toEqual(value);
  expect(fetch).toHaveBeenLastCalledWith("/api/v1/library/export",expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer fixture"}}));
});
test.each([{...value,ownerId:"00000000-0000-4000-8000-000000000002"},{...value,data:{...data,reports:undefined}}])("foreign or incomplete files cannot be downloaded",async invalid=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(Response.json({id:owner})).mockResolvedValueOnce(Response.json(invalid)));
  await expect(readAccountExport("fixture")).rejects.toThrow("INVALID_RESPONSE");
});
