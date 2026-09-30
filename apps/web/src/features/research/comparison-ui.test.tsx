import {cleanup,render,screen,within} from "@testing-library/react";
import {afterEach,expect,test} from "vitest";
import {ComparisonReport} from "./comparison-ui";
import type {ComparisonReportView} from "./comparison-client";

const release="00000000-0000-4000-8000-000000000001";
const origin={item_id:"00000000-0000-4000-8000-000000000002",release_id:release};
const candidate={item_id:"00000000-0000-4000-8000-000000000003",release_id:release};
const originEvidence="00000000-0000-4000-8000-000000000004";
const candidateEvidence="00000000-0000-4000-8000-000000000005";
const originClaim={kind:"tag",key:"fruit",value:"果香",evidenceIds:[originEvidence]};
const candidateClaim={kind:"tag",key:"fruit",value:"果香",evidenceIds:[candidateEvidence]};
const view:ComparisonReportView={schemaVersion:4,reportId:release,taskId:release,conditionsRevision:2,catalogReleaseId:release,evaluatedOn:"2026-09-30",comparison:{schemaVersion:4,intent:{mode:"similar",smoke_comparison:false},unresolved:[],unlistedName:null,candidates:[{candidate,mode:"similar",origin,commonTags:["fruit"],originClaims:[originClaim],candidateClaims:[candidateClaim],originDescription:{...originClaim,kind:"fact",key:"producer_tasting_notes",value:"熟果與香料"},candidateDescription:{...candidateClaim,kind:"fact",key:"producer_tasting_notes",value:"果香與蜂蜜"},difference:null,exploreClaims:[]}]},items:[{reference:origin,name:"起點酒款",sources:[{evidenceId:originEvidence,url:"https://origin.example/notes",publisher:"起點原廠",checkedOn:"2026-09-29"}]},{reference:candidate,name:"候選酒款",sources:[{evidenceId:candidateEvidence,url:"https://candidate.example/notes",publisher:"候選原廠",checkedOn:"2026-09-28"}]}]};
afterEach(cleanup);

test("reviewed comparison renders both sides with their own citations and no invented intensity",()=>{
  render(<ComparisonReport view={view}/>);
  const region=screen.getByRole("region",{name:"候選酒款的比較"});
  expect(within(region).getByText("起點：起點酒款")).toBeTruthy();
  expect(within(region).getByText("熟果與香料")).toBeTruthy();
  expect(within(region).getByText("果香與蜂蜜")).toBeTruthy();
  expect(within(region).getByRole("link",{name:"起點原廠"}).getAttribute("href")).toBe("https://origin.example/notes");
  expect(within(region).getByRole("link",{name:"候選原廠"}).getAttribute("href")).toBe("https://candidate.example/notes");
  expect(region.textContent).not.toMatch(/更低|更高|更少|更強/);
});

test("unlisted origin remains explicitly unresolved without a substitute candidate",()=>{
  render(<ComparisonReport view={{...view,comparison:{...view.comparison,candidates:[],unlistedName:"未收錄酒款",unresolved:["目前沒有已覆核的起點資料。"]},items:[]}}/>);
  expect(screen.getByText("未收錄起點：未收錄酒款")).toBeTruthy();
  expect(screen.getByText("目前沒有已覆核的起點資料。")).toBeTruthy();
  expect(screen.queryByRole("region",{name:"候選酒款的比較"})).toBeNull();
});
