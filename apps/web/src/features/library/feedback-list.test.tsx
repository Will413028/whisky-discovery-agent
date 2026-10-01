import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {BottleFeedbackLibrary} from "./feedback-list";
import {listBottleFeedback,readBottleFeedback} from "./feedback-client";
vi.mock("./feedback-client",async original=>({...await original<typeof import("./feedback-client")>(),listBottleFeedback:vi.fn(),readBottleFeedback:vi.fn()}));
const auth=vi.hoisted(()=>({isAuthenticated:true,isLoading:false,user:{sub:"owner-a"},getAccessTokenSilently:vi.fn().mockResolvedValue("fixture"),loginWithRedirect:vi.fn()}));
vi.mock("@auth0/auth0-react",()=>({useAuth0:()=>auth}));
afterEach(()=>{cleanup();vi.resetAllMocks();vi.unstubAllGlobals();auth.user={sub:"owner-a"};auth.getAccessTokenSilently.mockResolvedValue("fixture");});
const id="00000000-0000-4000-8000-000000000001";
const feedback={schemaVersion:1 as const,id,bottleVersionId:id,revision:1,wantToExplore:true,tasting:"not_tasted" as const,tastingReason:"",createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
test("reopening a removed favorite preserves its identity and provides editing and catalog exits",async()=>{
  vi.mocked(listBottleFeedback).mockResolvedValue({schemaVersion:1,items:[feedback],nextCursor:null});
  vi.mocked(readBottleFeedback).mockResolvedValue(feedback);
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({releaseId:null,evaluatedOn:"2026-10-01",pricePolicyVersion:"fixture",items:[]})));
  render(<BottleFeedbackLibrary/>);
  expect(await screen.findByText(/目前庫內無法解析此版本/)).toBeTruthy();
  expect(await screen.findByLabelText("想探索（收藏）")).toBeTruthy();
  expect(screen.getByRole("link",{name:"查看目前已覆核酒款"})).toBeTruthy();
});
test("switching accounts immediately removes previous private feedback",async()=>{
  vi.mocked(listBottleFeedback).mockResolvedValueOnce({schemaVersion:1,items:[{...feedback,tasting:"disliked",tastingReason:"第一帳號的私人原因"}],nextCursor:null}).mockResolvedValueOnce({schemaVersion:1,items:[],nextCursor:null});
  vi.mocked(readBottleFeedback).mockResolvedValue(feedback);
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({releaseId:null,evaluatedOn:"2026-10-01",pricePolicyVersion:"fixture",items:[]})));
  const view=render(<BottleFeedbackLibrary/>);
  await screen.findByText("第一帳號的私人原因");
  auth.user={sub:"owner-b"};view.rerender(<BottleFeedbackLibrary/>);
  expect(screen.queryByText("第一帳號的私人原因")).toBeNull();
  await screen.findByText("尚未保存收藏或品飲回饋。");
});

test("a failed first-page refresh retries that page rather than appending the old next cursor",async()=>{
  vi.mocked(listBottleFeedback).mockResolvedValueOnce({schemaVersion:1,items:[feedback],nextCursor:"previous-next-page"}).mockRejectedValueOnce(new Error("refresh unavailable")).mockResolvedValueOnce({schemaVersion:1,items:[],nextCursor:null});
  vi.mocked(readBottleFeedback).mockResolvedValue(feedback);
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json({releaseId:null,evaluatedOn:"2026-10-01",pricePolicyVersion:"fixture",items:[]})));
  render(<BottleFeedbackLibrary/>);
  await screen.findByRole("button",{name:"讀取更多回饋"});
  fireEvent.click(screen.getByRole("button",{name:"更新列表與目前酒款"}));
  fireEvent.click(await screen.findByRole("button",{name:"重新讀取回饋"}));
  await waitFor(()=>expect(listBottleFeedback).toHaveBeenCalledTimes(3));
  expect(vi.mocked(listBottleFeedback).mock.calls[2]?.[1]).toBeNull();
  await screen.findByText("尚未保存收藏或品飲回饋。");
});
