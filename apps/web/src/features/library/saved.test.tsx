import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {SavedConclusions} from "./saved";
import {listConclusions} from "./client";
const auth=vi.hoisted(()=>({isAuthenticated:true,isLoading:false,user:{sub:"owner-a"},getAccessTokenSilently:vi.fn().mockResolvedValue("fixture")}));
vi.mock("@auth0/auth0-react",()=>({useAuth0:()=>auth}));
vi.mock("./client",()=>({listConclusions:vi.fn(),revisitConclusion:vi.fn().mockRejectedValue(new Error("fixture unavailable"))}));
afterEach(()=>{cleanup();vi.clearAllMocks();auth.user={sub:"owner-a"};});
const id="00000000-0000-4000-8000-000000000001";
test("saved choices render as historical and disappear immediately when the account changes",async()=>{
  vi.mocked(listConclusions).mockResolvedValueOnce({schemaVersion:1,planId:id,items:[{id,taskId:id,reason:"第一帳號私人理由",tradeoff:"放棄煙燻",outcome:"no_suitable",conditionsRevision:1,evaluatedOn:"2026-10-01",createdAt:"2026-10-01T00:00:00Z",conditions:{goal:"歷史條件"}}],nextCursor:null} as Awaited<ReturnType<typeof listConclusions>>).mockImplementationOnce(()=>new Promise(()=>{}));
  const view=render(<SavedConclusions planId={id}/>);
  await screen.findByText("第一帳號私人理由");
  expect(screen.getByText(/歷史結論/)).toBeTruthy();
  expect(screen.getByText(/未重新查詢前/)).toBeTruthy();
  expect(await screen.findByRole("button",{name:"重新查詢目前價格"})).toBeTruthy();
  auth.user={sub:"owner-b"};view.rerender(<SavedConclusions planId={id}/>);
  expect(screen.queryByText("第一帳號私人理由")).toBeNull();
});
test("a selected historical conclusion identifies which bottle was chosen",async()=>{
  vi.mocked(listConclusions).mockResolvedValueOnce({schemaVersion:1,planId:id,items:[{id,taskId:id,reason:"明確選擇理由",tradeoff:"",outcome:"selected",selectedBottleName:"合成候選十二年",conditionsRevision:1,createdAt:"2026-10-01T00:00:00Z",conditions:{goal:"歷史條件"}}],nextCursor:null} as Awaited<ReturnType<typeof listConclusions>>);
  render(<SavedConclusions planId={id}/>);
  expect(await screen.findByText("當時選擇：合成候選十二年")).toBeTruthy();
});
