import {act,cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {AccountExportButton} from "./export-ui";
import {readAccountExport} from "./export-client";
vi.mock("./export-client",()=>({readAccountExport:vi.fn()}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals();});
test("only a validated completed export triggers a file download",async()=>{
  const create=vi.fn(()=>"blob:fixture");vi.stubGlobal("URL",class extends URL{static createObjectURL=create;static revokeObjectURL=vi.fn();});
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
  const completeFile=new Blob(["synthetic complete export"]);
  vi.mocked(readAccountExport).mockResolvedValue(completeFile as unknown as Awaited<ReturnType<typeof readAccountExport>>);
  render(<AccountExportButton token={async()=>"fixture"}/>);
  fireEvent.click(screen.getByRole("button",{name:"匯出我的資料"}));
  await screen.findByText("匯出檔已準備，瀏覽器會下載。");
  expect((create.mock.calls[0] as unknown as [Blob])[0].size).toBe(completeFile.size);
  expect(click).toHaveBeenCalledTimes(1);
});
test("an account change before token resolution stops the old export",async()=>{
  let finish:(value:string)=>void=()=>{};const old=()=>new Promise<string>(resolve=>{finish=resolve;});
  const view=render(<AccountExportButton token={old}/>);
  fireEvent.click(screen.getByRole("button",{name:"匯出我的資料"}));
  view.rerender(<AccountExportButton token={async()=>"new-owner"}/>);
  await act(async()=>{finish("old-owner");});
  expect(readAccountExport).not.toHaveBeenCalled();
});
