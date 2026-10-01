import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, test, vi} from "vitest";
import {PlanHistory} from "./history";

const id = "00000000-0000-4000-8000-000000000001";
const taskId = "00000000-0000-4000-8000-000000000002";
const item = {createdAt:"2026-09-29T00:00:00Z",task:{taskId,conditionsRevision:1,status:"completed"}};
const read = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({isAuthenticated:true,isLoading:false,user:{sub:"owner-a"},getAccessTokenSilently:vi.fn().mockResolvedValue("fixture-token")}));
vi.mock("./history-client", () => ({listHistory:read}));
vi.mock("@auth0/auth0-react", () => ({useAuth0:() => auth}));
afterEach(() => {cleanup(); vi.resetAllMocks(); auth.isAuthenticated=true; auth.user={sub:"owner-a"}; auth.getAccessTokenSilently.mockResolvedValue("fixture-token");});

test("history keeps old revision and creation date visible; failed pagination preserves previous results", async () => {
  read.mockResolvedValueOnce({items:[item],nextCursor:"opaque-cursor"})
    .mockRejectedValueOnce(new Error("REQUEST_FAILED"))
    .mockResolvedValueOnce({items:[{...item,task:{...item.task,taskId:id,conditionsRevision:2,status:"queued"}}],nextCursor:null});
  render(<PlanHistory planId={id} revision={2} />);
  expect(await screen.findByText("歷史條件版本 1" )).toBeTruthy();
  expect(screen.getByText("2026-09-29T00:00:00Z").closest("time")?.getAttribute("datetime")).toBe(item.createdAt);
  expect(screen.getByRole("link",{name:"查看研究 completed"}).getAttribute("href")).toBe(`/research/${taskId}`);
  fireEvent.click(screen.getByRole("button",{name:"讀取更多研究"}));
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取研究紀錄");
  expect(screen.getByText("歷史條件版本 1")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"重新讀取研究紀錄"}));
  expect(await screen.findByText("目前條件版本 2")).toBeTruthy();
  expect(read.mock.calls.map(call=>call[2])).toEqual([null,"opaque-cursor","opaque-cursor"]);
});

test("initial read failure is not an empty history", async () => {
  read.mockRejectedValue(new Error("REQUEST_FAILED"));
  render(<PlanHistory planId={id} revision={1} />);
  await screen.findByRole("alert");
  expect(screen.queryByText("尚未有研究紀錄。")).toBeNull();
});

test("completed history offers an explicit restart direction without treating an unfinished task as reusable",async()=>{
  read.mockResolvedValue({items:[item,{...item,task:{...item.task,taskId:id,status:"needs_input"}}],nextCursor:null});
  render(<PlanHistory planId={id} revision={2}/>);
  const link=await screen.findByRole("link",{name:"查看可沿用的探索方向"});
  expect(link.getAttribute("href")).toBe(`/plans/${id}?restartTaskId=${taskId}`);
  expect(screen.getAllByRole("link",{name:"查看可沿用的探索方向"})).toHaveLength(1);
});

test("confirmed revision changes reread superseded task state and fence an older page",async()=>{
  let complete!:(value:unknown)=>void;
  read.mockResolvedValueOnce({items:[{...item,task:{...item.task,status:"needs_input"}}],nextCursor:"old-page"})
    .mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;}))
    .mockResolvedValueOnce({items:[{...item,task:{...item.task,status:"superseded"}}],nextCursor:null});
  const view=render(<PlanHistory planId={id} revision={1} />);
  await screen.findByRole("link",{name:"查看研究 needs_input"});
  fireEvent.click(screen.getByRole("button",{name:"讀取更多研究"}));
  await waitFor(()=>expect(read).toHaveBeenCalledTimes(2));
  view.rerender(<PlanHistory planId={id} revision={2} />);
  expect(await screen.findByRole("link",{name:"查看研究 superseded"})).toBeTruthy();
  complete({items:[{...item,task:{...item.task,status:"needs_input"}}],nextCursor:null});
  await new Promise(resolve=>setTimeout(resolve,0));
  expect(screen.queryByRole("link",{name:"查看研究 needs_input"})).toBeNull();
  expect(read.mock.calls[2][2]).toBeNull();
});

test("subject change fences a late historical page from the previous owner", async () => {
  let complete!:(value:unknown)=>void;
  read.mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;})).mockResolvedValueOnce({items:[],nextCursor:null});
  const view = render(<PlanHistory planId={id} revision={2} />);
  await waitFor(()=>expect(read).toHaveBeenCalledOnce());
  auth.user={sub:"owner-b"};
  view.rerender(<PlanHistory planId={id} revision={2} />);
  await screen.findByText("尚未有研究紀錄。");
  complete({items:[item],nextCursor:null});
  await new Promise(resolve=>setTimeout(resolve,0));
  expect(screen.queryByText("歷史條件版本 1")).toBeNull();
});
