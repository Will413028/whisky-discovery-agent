import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {LongTermPreferencesEditor} from "./preferences-editor";
import {PreferencesRejected,readLongTermPreferences,saveLongTermPreferences} from "./preferences-client";
vi.mock("./preferences-client",async original=>({...await original<typeof import("./preferences-client")>(),readLongTermPreferences:vi.fn(),saveLongTermPreferences:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const token=async()=>"fixture";
const entry={description:"果香",intent:"prefer" as const,strength:"soft" as const,certainty:"user_stated" as const,statement:"我明確表示喜歡果香",sourceFeedbackId:null,sourceFeedbackRevision:null};
const empty={schemaVersion:1 as const,revision:0,preferences:[],updatedAt:null};
const saved={schemaVersion:1 as const,revision:1,preferences:[entry],updatedAt:"2026-10-01T00:00:00Z"};
async function add(){
  fireEvent.change(await screen.findByLabelText("偏好特徵"),{target:{value:"果香"}});
  fireEvent.change(screen.getByLabelText("我的明確陳述"),{target:{value:"我明確表示喜歡果香"}});
  fireEvent.click(screen.getByRole("button",{name:"加入明確偏好"}));
}
test("an explicit preference saves separately without a budget or inferred tags",async()=>{
  vi.mocked(readLongTermPreferences).mockResolvedValue(empty);vi.mocked(saveLongTermPreferences).mockResolvedValue(saved);
  render(<LongTermPreferencesEditor token={token}/>);await add();
  fireEvent.click(screen.getByRole("button",{name:"保存長期偏好"}));
  await screen.findByText("長期偏好已保存。");
  const command=vi.mocked(saveLongTermPreferences).mock.calls[0]?.[0];
  expect(command?.preferences).toEqual([entry]);expect(command?.expectedRevision).toBe(0);
  expect(command).not.toHaveProperty("budgetTwd");
});
test("an unknown profile result retries the identical immutable command",async()=>{
  vi.mocked(readLongTermPreferences).mockResolvedValue(empty);vi.mocked(saveLongTermPreferences).mockRejectedValueOnce(new Error("lost reply")).mockResolvedValueOnce(saved);
  render(<LongTermPreferencesEditor token={token}/>);await add();
  fireEvent.click(screen.getByRole("button",{name:"保存長期偏好"}));
  fireEvent.click(await screen.findByRole("button",{name:"重送同一偏好"}));
  await screen.findByText("長期偏好已保存。");
  expect(vi.mocked(saveLongTermPreferences).mock.calls[0]?.[0]).toEqual(vi.mocked(saveLongTermPreferences).mock.calls[1]?.[0]);
});
test("a known conflict reloads the latest profile before further editing",async()=>{
  vi.mocked(readLongTermPreferences).mockResolvedValueOnce(empty).mockResolvedValueOnce({...saved,revision:2,preferences:[{...entry,description:"橡木",intent:"avoid",statement:"我明確排斥橡木"}]});
  vi.mocked(saveLongTermPreferences).mockRejectedValueOnce(new PreferencesRejected("REVISION_CONFLICT",409));
  render(<LongTermPreferencesEditor token={token}/>);await add();
  fireEvent.click(screen.getByRole("button",{name:"保存長期偏好"}));
  fireEvent.click(await screen.findByRole("button",{name:"重新讀取長期偏好"}));
  await screen.findByText("我明確排斥橡木");
  await waitFor(()=>expect(saveLongTermPreferences).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("button",{name:"重送同一偏好"})).toBeNull();
});
