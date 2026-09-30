import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {ReportConclusion} from "./report-choice";
import {readConclusionContext} from "./client";
vi.mock("./client",async importOriginal=>({...await importOriginal<typeof import("./client")>(),readConclusionContext:vi.fn(),saveConclusion:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const id="00000000-0000-4000-8000-000000000001";
const getToken=async()=>"fixture";
test.each([1,2])("only a report matching the current conditions exposes the save form (current %s)",async current=>{
  vi.mocked(readConclusionContext).mockResolvedValue({schemaVersion:1,planId:id,taskId:id,reportId:id,conditionsRevision:1,currentConditionsRevision:current});
  render(<ReportConclusion reportId={id} taskId={id} revision={1} candidates={[]} getToken={getToken}/>);
  if(current===1) await screen.findByRole("button",{name:"保存探索結論"});
  else {await screen.findByText(/這份報告屬於歷史條件/);expect(screen.queryByRole("button",{name:"保存探索結論"})).toBeNull();}
});
