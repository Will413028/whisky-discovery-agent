import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {BottleFeedbackEditor} from "./feedback-editor";
import {FeedbackRejected,readBottleFeedback,saveBottleFeedback} from "./feedback-client";
vi.mock("./feedback-client",async original=>({...await original<typeof import("./feedback-client")>(),readBottleFeedback:vi.fn(),saveBottleFeedback:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const id="00000000-0000-4000-8000-000000000001";
const token=async()=>"fixture";
const base={schemaVersion:1 as const,id,bottleVersionId:id,revision:1,wantToExplore:true,tasting:"not_tasted" as const,tastingReason:"",createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
test("a favorite stays independent of tasting and is successful only after the API receipt",async()=>{
  vi.mocked(readBottleFeedback).mockResolvedValue(null);
  vi.mocked(saveBottleFeedback).mockResolvedValue(base);
  render(<BottleFeedbackEditor version={id} name="合成酒款" token={token}/>);
  fireEvent.click(await screen.findByLabelText("想探索（收藏）"));
  fireEvent.click(screen.getByRole("button",{name:"保存酒款回饋"}));
  await screen.findByText("酒款回饋已保存。");
  expect(saveBottleFeedback).toHaveBeenCalledWith(expect.objectContaining({bottleVersionId:id,expectedRevision:0,wantToExplore:true,tasting:"not_tasted",tastingReason:""}),"fixture");
});
test("an unknown write result retries the same immutable payload and key",async()=>{
  vi.mocked(readBottleFeedback).mockResolvedValue(null);
  vi.mocked(saveBottleFeedback).mockRejectedValueOnce(new Error("lost reply")).mockResolvedValueOnce(base);
  render(<BottleFeedbackEditor version={id} name="合成酒款" token={token}/>);
  fireEvent.click(await screen.findByLabelText("想探索（收藏）"));
  fireEvent.click(screen.getByRole("button",{name:"保存酒款回饋"}));
  fireEvent.click(await screen.findByRole("button",{name:"重送同一回饋"}));
  await screen.findByText("酒款回饋已保存。");
  expect(vi.mocked(saveBottleFeedback).mock.calls[0]?.[0]).toEqual(vi.mocked(saveBottleFeedback).mock.calls[1]?.[0]);
});
test("a known revision rejection reloads current feedback before another edit",async()=>{
  vi.mocked(readBottleFeedback).mockResolvedValueOnce(null).mockResolvedValueOnce({...base,revision:2,tasting:"disliked",tastingReason:"另一分頁已修改"});
  vi.mocked(saveBottleFeedback).mockRejectedValueOnce(new FeedbackRejected("REVISION_CONFLICT",409));
  render(<BottleFeedbackEditor version={id} name="合成酒款" token={token}/>);
  fireEvent.click(await screen.findByLabelText("想探索（收藏）"));
  fireEvent.click(screen.getByRole("button",{name:"保存酒款回饋"}));
  fireEvent.click(await screen.findByRole("button",{name:"重新讀取回饋"}));
  await waitFor(()=>expect((screen.getByLabelText("品飲原因") as HTMLTextAreaElement).value).toBe("另一分頁已修改"));
  expect(saveBottleFeedback).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button",{name:"重送同一回饋"})).toBeNull();
});

test("a token arriving after the editor unmounts never sends the previous session's write",async()=>{
  let resolve!:(value:string)=>void;
  const pending=new Promise<string>(done=>{resolve=done;});
  const access=vi.fn().mockResolvedValueOnce("fixture").mockReturnValueOnce(pending);
  vi.mocked(readBottleFeedback).mockResolvedValue(null);
  const view=render(<BottleFeedbackEditor version={id} name="合成酒款" token={access}/>);
  fireEvent.click(await screen.findByRole("button",{name:"保存酒款回饋"}));
  view.unmount();resolve("previous-session-token");
  await pending;
  await new Promise(done=>setTimeout(done,0));
  expect(saveBottleFeedback).not.toHaveBeenCalled();
});
