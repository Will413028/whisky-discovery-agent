import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, test, vi} from "vitest";
import {PlanDetail, Plans} from "./ui";
import {RequestRejected} from "./client";

const id = "00000000-0000-4000-8000-000000000001";
const commandId = "00000000-0000-4000-8000-000000000002";
const base = {id, conditionsRevision:1, conditions:{schema_version:1, entry:"beginner", goal:"保留果香", budget_twd:"1000", preferences:[], starting_bottle:null}};
const receipt = {id:commandId, kind:"plan.change_conditions", targetId:id, status:"pending", result:null};
const api = vi.hoisted(() => ({readPlan:vi.fn(),patchPlan:vi.fn(),readControl:vi.fn(),listPlans:vi.fn()}));
const auth = vi.hoisted(() => ({isAuthenticated:true,isLoading:false,getAccessTokenSilently:vi.fn().mockResolvedValue("fixture-token"),loginWithRedirect:vi.fn()}));
const research = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
vi.mock("./client", async () => ({...await vi.importActual<typeof import("./client")>("./client"), ...api}));
vi.mock("@auth0/auth0-react", () => ({useAuth0:() => auth}));
vi.mock("next/navigation", () => ({useRouter:() => ({push})}));
vi.mock("../research", () => ({startResearch:research}));
afterEach(() => {cleanup(); vi.resetAllMocks(); auth.isAuthenticated = true; auth.getAccessTokenSilently.mockResolvedValue("fixture-token");});

test("plan pagination preserves earlier plans on failure and retries the same cursor", async () => {
  const other = {...base,id:commandId,conditions:{...base.conditions,goal:"探索甜香"}};
  api.listPlans.mockResolvedValueOnce({items:[base],nextCursor:"cursor-one"})
    .mockRejectedValueOnce(new Error("REQUEST_FAILED"))
    .mockResolvedValueOnce({items:[other],nextCursor:null});
  render(<Plans />);
  expect(await screen.findByRole("link", {name:"保留果香"})).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name:"讀取更多計畫"}));
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取探索計畫");
  expect(screen.getByRole("link", {name:"保留果香"})).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name:"重新讀取計畫"}));
  expect(await screen.findByRole("link", {name:"探索甜香"})).toBeTruthy();
  expect(screen.getByRole("link", {name:"保留果香"}).getAttribute("href")).toBe(`/plans/${id}`);
  expect(api.listPlans.mock.calls.map(call => call[1])).toEqual([null,"cursor-one","cursor-one"]);
});

test("plan load errors are explicit and can be retried", async () => {
  api.readPlan.mockRejectedValueOnce(new Error("REQUEST_FAILED")).mockResolvedValueOnce(base);
  render(<PlanDetail planId={id} />);
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取計畫");
  fireEvent.click(screen.getByRole("button", {name:"重新讀取計畫"}));
  expect(await screen.findByDisplayValue("保留果香")).toBeTruthy();
  expect(api.readPlan).toHaveBeenCalledTimes(2);
});

test("a lost patch response retries the same base and key; only confirmed revision may start new research", async () => {
  api.readPlan.mockResolvedValueOnce(base).mockResolvedValueOnce({...base,conditionsRevision:2,conditions:{...base.conditions,budget_twd:"900"}});
  api.patchPlan.mockRejectedValueOnce(new Error("REQUEST_FAILED")).mockResolvedValueOnce({...receipt,status:"intent_confirmed"});
  api.readControl.mockResolvedValue({...receipt,status:"completed",result:{conditionsRevision:"2"}});
  research.mockResolvedValue({taskId:commandId});
  render(<PlanDetail planId={id} />);
  const budget = await screen.findByLabelText("本次預算上限（新台幣，可留空）");
  fireEvent.change(budget, {target:{value:"900"}});
  fireEvent.click(screen.getByRole("button", {name:"保存指定修改"}));
  expect((await screen.findByRole("alert")).textContent).toContain("變更暫時無法確認");
  const body = api.patchPlan.mock.calls[0][2];
  expect(body).toMatchObject({expectedRevision:1,baseConditions:base.conditions,patch:{budget_twd:"900"}});
  expect(body.patch).not.toHaveProperty("goal");
  fireEvent.click(screen.getByRole("button", {name:"重試同一變更"}));
  expect(await screen.findByText("變更等待確認；尚未建立新研究。")).toBeTruthy();
  expect(api.patchPlan.mock.calls[1][2]).toEqual(body);
  expect((screen.getByRole("button", {name:"使用已保存條件開始研究"}) as HTMLButtonElement).disabled).toBe(true);
  expect(research).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name:"重新確認變更"}));
  expect(await screen.findByText("條件版本：2")).toBeTruthy();
  expect(api.readControl).toHaveBeenCalledWith(commandId,"fixture-token");
  fireEvent.click(screen.getByRole("button", {name:"使用已保存條件開始研究"}));
  await waitFor(() => expect(push).toHaveBeenCalledWith(`/research/${commandId}`));
  expect(research.mock.calls[0][1]).toMatchObject({id,conditionsRevision:2});
});

test("sign-out prevents a late command completion from reading or revealing the saved plan", async () => {
  let complete!: (value:typeof receipt) => void;
  api.readPlan.mockResolvedValue(base);
  api.patchPlan.mockResolvedValue({...receipt,status:"intent_confirmed"});
  api.readControl.mockImplementation(() => new Promise(resolve => {complete = resolve;}));
  const view = render(<PlanDetail planId={id} />);
  fireEvent.change(await screen.findByLabelText("本次預算上限（新台幣，可留空）"), {target:{value:"900"}});
  fireEvent.click(screen.getByRole("button", {name:"保存指定修改"}));
  await screen.findByText("變更等待確認；尚未建立新研究。");
  fireEvent.click(screen.getByRole("button", {name:"重新確認變更"}));
  await waitFor(() => expect(api.readControl).toHaveBeenCalledOnce());
  auth.isAuthenticated = false;
  view.rerender(<PlanDetail planId={id} />);
  await screen.findByRole("button", {name:"登入查看探索計畫"});
  complete({...receipt,status:"completed"});
  await new Promise(resolve => setTimeout(resolve,0));
  expect(api.readPlan).toHaveBeenCalledOnce();
  expect(screen.queryByDisplayValue("保留果香")).toBeNull();
  expect(research).not.toHaveBeenCalled();
});

test("a lost research response retries the same saved revision, thread, run and key", async () => {
  api.readPlan.mockResolvedValue(base);
  research.mockRejectedValueOnce(new Error("REQUEST_FAILED")).mockResolvedValueOnce({taskId:commandId});
  render(<PlanDetail planId={id} />);
  await screen.findByDisplayValue("保留果香");
  fireEvent.click(screen.getByRole("button", {name:"使用已保存條件開始研究"}));
  expect((await screen.findByRole("alert")).textContent).toContain("委託暫時無法確認");
  fireEvent.click(screen.getByRole("button", {name:"使用已保存條件開始研究"}));
  await waitFor(() => expect(push).toHaveBeenCalledWith(`/research/${commandId}`));
  expect(research.mock.calls[1]).toEqual(research.mock.calls[0]);
  expect(api.patchPlan).not.toHaveBeenCalled();
});

test("pending receipt retry resubmits the same command to recover an unstarted workflow", async () => {
  api.readPlan.mockResolvedValueOnce(base).mockResolvedValueOnce({...base,conditionsRevision:2,conditions:{...base.conditions,budget_twd:"900"}});
  api.patchPlan.mockResolvedValueOnce(receipt).mockResolvedValueOnce({...receipt,status:"completed",result:{conditionsRevision:"2"}});
  api.readControl.mockResolvedValue(receipt);
  render(<PlanDetail planId={id} />);
  fireEvent.change(await screen.findByLabelText("本次預算上限（新台幣，可留空）"), {target:{value:"900"}});
  fireEvent.click(screen.getByRole("button", {name:"保存指定修改"}));
  await screen.findByText("變更等待確認；尚未建立新研究。");
  fireEvent.click(screen.getByRole("button", {name:"重新確認變更"}));
  expect(await screen.findByText("條件版本：2")).toBeTruthy();
  expect(api.patchPlan.mock.calls[1][2]).toEqual(api.patchPlan.mock.calls[0][2]);
  expect(api.readControl).not.toHaveBeenCalled();
});

test.each([409,422] as const)("definite %s rejection offers a fresh plan without replaying the refused attempt", async rejection => {
  api.readPlan.mockResolvedValueOnce(base).mockResolvedValueOnce({...base,conditionsRevision:2,conditions:{...base.conditions,budget_twd:"1100"}});
  api.patchPlan.mockRejectedValue(new RequestRejected(rejection));
  render(<PlanDetail planId={id} />);
  fireEvent.change(await screen.findByLabelText("本次預算上限（新台幣，可留空）"), {target:{value:"900"}});
  fireEvent.click(screen.getByRole("button", {name:"保存指定修改"}));
  expect((await screen.findByRole("alert")).textContent).toContain("變更未受理");
  fireEvent.click(screen.getByRole("button", {name:"重新讀取計畫"}));
  expect(await screen.findByText("條件版本：2")).toBeTruthy();
  expect(await screen.findByDisplayValue("1100")).toBeTruthy();
  expect(api.patchPlan).toHaveBeenCalledOnce();
  expect((screen.getByRole("button", {name:"使用已保存條件開始研究"}) as HTMLButtonElement).disabled).toBe(false);
});
