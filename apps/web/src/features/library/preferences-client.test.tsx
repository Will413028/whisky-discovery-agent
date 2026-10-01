import {afterEach,expect,test,vi} from "vitest";
import {PreferencesRejected,readLongTermPreferences,saveLongTermPreferences} from "./preferences-client";
afterEach(()=>vi.unstubAllGlobals());
const preference={description:"果香",intent:"prefer" as const,strength:"soft" as const,certainty:"user_stated" as const,statement:"我明確表示喜歡果香",sourceFeedbackId:null,sourceFeedbackRevision:null};
const saved={schemaVersion:1 as const,revision:1,preferences:[preference],updatedAt:"2026-10-01T00:00:00Z"};
const command={schemaVersion:1 as const,key:"explicit-profile",expectedRevision:0,preferences:[preference]};
test("private preferences read a validated current profile without budget",async()=>{
  const fetch=vi.fn(async()=>Response.json(saved));vi.stubGlobal("fetch",fetch);
  expect(await readLongTermPreferences("fixture")).toEqual(saved);
  expect(fetch).toHaveBeenCalledWith("/api/v1/library/preferences",expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer fixture"}}));
});
test("preferences save a fixed command and verify the returned revision and values",async()=>{
  const fetch=vi.fn(async()=>Response.json(saved,{status:201}));vi.stubGlobal("fetch",fetch);
  expect(await saveLongTermPreferences(command,"fixture")).toEqual(saved);
  expect(fetch).toHaveBeenCalledWith("/api/v1/library/preferences",expect.objectContaining({method:"POST",body:JSON.stringify(command)}));
});
test("known profile conflict is distinct from an unknown network result",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code:"SOURCE_FEEDBACK_CHANGED"},{status:409})));
  await expect(saveLongTermPreferences(command,"fixture")).rejects.toBeInstanceOf(PreferencesRejected);
});
test("disabled actor is a known rejection and keeps its status",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({code:"ACTOR_DISABLED"},{status:403})));
  await expect(saveLongTermPreferences(command,"fixture")).rejects.toMatchObject({code:"ACTOR_DISABLED",status:403});
});
