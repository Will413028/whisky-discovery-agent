import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {ApplyLongTermPreferences} from "./apply-preferences";
import {readLongTermPreferences} from "./preferences-client";
vi.mock("./preferences-client",async original=>({...await original<typeof import("./preferences-client")>(),readLongTermPreferences:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const token=async()=>"fixture";
const entry={description:"果香",intent:"prefer" as const,strength:"soft" as const,certainty:"user_stated" as const,statement:"我明確喜歡果香",sourceFeedbackId:null,sourceFeedbackRevision:null};
test("a new exploration only applies saved preferences after explicit selection",async()=>{
  vi.mocked(readLongTermPreferences).mockResolvedValue({schemaVersion:1,revision:1,preferences:[entry],updatedAt:"2026-10-01T00:00:00Z"});
  const onChange=vi.fn();render(<ApplyLongTermPreferences token={token} onChange={onChange}/>);
  const checkbox=await screen.findByLabelText("套用 果香");
  expect((checkbox as HTMLInputElement).checked).toBe(false);expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(checkbox);expect(onChange).toHaveBeenCalledWith([entry]);
});
test("failed preference reads stay unknown rather than pretending there is no saved profile",async()=>{
  vi.mocked(readLongTermPreferences).mockRejectedValue(new Error("unavailable"));
  render(<ApplyLongTermPreferences token={token} onChange={vi.fn()}/>);
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取已存偏好");
  expect(screen.queryByText("尚未保存長期偏好。")).toBeNull();
});
