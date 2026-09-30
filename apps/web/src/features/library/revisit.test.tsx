import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {CurrentQualification} from "./revisit";
import {revisitConclusion,type Conclusion,type ConclusionRevisit} from "./client";
vi.mock("./client",()=>({revisitConclusion:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const id="00000000-0000-4000-8000-000000000001";
const saved={id,planId:id,taskId:id,conditionsRevision:1,selectedVersionId:id,alternativeVersionIds:[],conditions:{budget_twd:"1000"},reason:"當時理由"} as unknown as Conclusion;
const token=async()=>"fixture";
const result={schemaVersion:1,conclusionId:id,planId:id,conditionsRevision:1,catalogReleaseId:id,evaluatedOn:"2026-10-01",pricePolicyVersion:"price-30d-v1",budgetTwd:"1000",items:[{bottleVersionId:id,availability:"resolved",name:"合成目前酒款",priceUpperBoundTwd:"1200",priceQualification:"qualified",budgetQualification:"over_budget",prices:[{id,amount:"1200",currency:"TWD",market:"TW",volumeMl:700,checkedOn:"2026-09-28",sourceUrl:"https://fixture.example/price"}]}]} as ConclusionRevisit;
test("reopening distinguishes current price qualification from the saved historical reasons",async()=>{
  vi.mocked(revisitConclusion).mockResolvedValue(result);
  render(<CurrentQualification saved={saved} token={token}/>);
  expect(await screen.findByText(/超出當時預算/)).toBeTruthy();
  expect(screen.getByText(/價格判定日期：2026-10-01/)).toBeTruthy();
  expect(screen.getByText(/1200 TWD／700 ml/)).toBeTruthy();
  expect(screen.getByRole("link",{name:"報價來源"}).getAttribute("href")).toBe("https://fixture.example/price");
});
test("a removed version keeps an explicit unresolved exit and never silently substitutes",async()=>{
  vi.mocked(revisitConclusion).mockResolvedValue({...result,items:[{bottleVersionId:id,availability:"unresolved",name:null,priceUpperBoundTwd:null,priceQualification:"unqualified",budgetQualification:"unknown",prices:[]}]});
  render(<CurrentQualification saved={saved} token={token}/>);
  expect(await screen.findByText(/目前庫內無法解析此版本/)).toBeTruthy();
  expect(screen.getByRole("link",{name:"重新選擇探索方向"}).getAttribute("href")).toBe(`/plans/${id}?restartTaskId=${id}`);
});
test("failed current qualification stays unknown and can retry without replacing saved history",async()=>{
  vi.mocked(revisitConclusion).mockRejectedValueOnce(new Error("unavailable")).mockResolvedValueOnce({...result,items:[{...result.items[0],priceUpperBoundTwd:null,priceQualification:"unqualified",budgetQualification:"unknown",prices:[]}]});
  render(<CurrentQualification saved={saved} token={token}/>);
  fireEvent.click(await screen.findByRole("button",{name:"重新查詢目前價格"}));
  expect(await screen.findByText(/價格資料不足，不能判為符合當時預算/)).toBeTruthy();
  await waitFor(()=>expect(revisitConclusion).toHaveBeenCalledTimes(2));
});
