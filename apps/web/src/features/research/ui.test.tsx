import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ResearchStart, ResearchTask } from "./ui";
import type { TaskView } from "./state";

const id = "00000000-0000-4000-8000-000000000001";
const questionId = "00000000-0000-4000-8000-000000000002";
const reportId = "00000000-0000-4000-8000-000000000003";
const selectedVersionId = "00000000-0000-4000-8000-000000000005";
const auth = vi.hoisted(() => ({
  isAuthenticated:true, isLoading:false, loginWithRedirect:vi.fn(),
  getAccessTokenSilently:vi.fn().mockResolvedValue("fixture-token"),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("@auth0/auth0-react", () => ({useAuth0:() => auth}));
vi.mock("next/navigation", () => ({useRouter:() => ({push, replace:vi.fn()})}));
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); auth.isAuthenticated = true;});

const waiting: TaskView = {
  schemaVersion:1, taskId:id, threadId:"00000000-0000-4000-8000-000000000004",
  conditionsRevision:1, viewVersion:3, status:"needs_input", stage:"等待版本補充",
  question:{id:questionId, prompt:"你指的是哪個版本？", choices:[{id:"00000000-0000-4000-8000-000000000006",label:"12 年"},{id:selectedVersionId,label:"15 年"}], waitingVersion:1, expiresAt:"2026-10-06T00:00:00Z"},
  reportId:null, error:null, observedAt:"2026-09-29T00:00:00Z", activeRunId:null,
};

test("beginner form creates a plan and starts a durable AG-UI turn before navigation", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(new URL(String(input), window.location.origin), init);
    requests.push(request);
    if (request.url.endsWith("/api/v1/tasks")) return Response.json([]);
    if (request.url.endsWith("/api/v1/plans")) return Response.json({id, conditionsRevision:1}, {status:201});
    if (request.url.endsWith("/agent")) {
      const command = await request.clone().json();
      return new Response(
        `data: ${JSON.stringify({type:"RUN_STARTED", threadId:command.threadId, runId:command.runId})}\n\n` +
        `data: ${JSON.stringify({type:"STATE_SNAPSHOT", snapshot:{...waiting, threadId:command.threadId, status:"queued", question:null}})}\n\n`,
        {headers:{"Content-Type":"text/event-stream"}},
      );
    }
    throw new Error(`Unexpected ${request.url}`);
  }));
  render(<ResearchStart />);
  fireEvent.change(screen.getByLabelText("想探索什麼風味？"), {target:{value:"果香"}});
  fireEvent.click(screen.getByRole("button", {name:"開始探索"}));
  await waitFor(() => expect(push).toHaveBeenCalledWith(`/research/${id}`));
  expect(await requests.find(request => request.url.endsWith("/api/v1/plans"))?.json()).toMatchObject({conditions:{entry:"beginner", goal:"果香"}});
  expect(await requests.find(request => request.url.endsWith("/agent"))?.json()).toMatchObject({forwardedProps:{type:"start", planId:id, conditionsRevision:1}});
  expect(requests.every(request => request.headers.get("authorization") === "Bearer fixture-token")).toBe(true);
});

test("start page offers owned unfinished task links after a new browser login", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(new URL(String(input), window.location.origin), init);
    requests.push(request);
    if (request.url.endsWith("/api/v1/tasks")) return Response.json([waiting]);
    throw new Error(`Unexpected ${request.url}`);
  }));
  render(<ResearchStart />);
  const link = await screen.findByRole("link", {name:"繼續上次探索"});
  expect(link.getAttribute("href")).toBe(`/research/${id}`);
  expect(requests[0].headers.get("authorization")).toBe("Bearer fixture-token");
});

test("task page reconnects the active AG-UI turn from its persisted run ID", async () => {
  const runId = "00000000-0000-4000-8000-000000000007";
  const queued: TaskView = {...waiting, status:"queued",stage:"等待研究開始",question:null,viewVersion:1,activeRunId:runId};
  const fetches: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(String(input), window.location.origin), init);
    fetches.push(new URL(request.url).pathname);
    if (request.url.endsWith(`/tasks/${id}`)) return Response.json(queued);
    if (request.url.endsWith("/agent/observe")) {
      expect(await request.clone().json()).toMatchObject({taskId:id,runId});
      return new Response(
        `data: ${JSON.stringify({type:"RUN_STARTED",threadId:queued.threadId,runId})}\n\n` +
        `data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot:waiting})}\n\n`,
        {headers:{"Content-Type":"text/event-stream"}},
      );
    }
    throw new Error(`Unexpected ${request.url}`);
  }));
  render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("你指的是哪個版本？")).toBeTruthy();
  expect(fetches).toContain("/agent/observe");
});

test("reopened task loads its persisted question, submits the versioned answer, and displays the saved report", async () => {
  let current: TaskView = waiting;
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(new URL(String(input), window.location.origin), init);
    requests.push(request);
    if (request.url.endsWith(`/tasks/${id}`)) return Response.json(current);
    if (request.url.endsWith(`/clarifications/${questionId}/answer`)) {
      current = {...waiting, viewVersion:5, status:"completed", question:null, reportId, stage:"報告完成"};
      return Response.json({id:crypto.randomUUID(), taskId:id, scope:"research.answer", acceptance:"accepted"});
    }
    if (request.url.endsWith(`/reports/${reportId}`)) return Response.json({id:reportId, taskId:id, summary:"已依補充版本重新查核", candidates:[]});
    throw new Error(`Unexpected ${request.url}`);
  }));
  const first = render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("你指的是哪個版本？")).toBeTruthy();
  first.unmount();
  render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("你指的是哪個版本？")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("15 年"));
  fireEvent.click(screen.getByRole("button", {name:"送出答覆"}));
  expect(await screen.findByText("已依補充版本重新查核")).toBeTruthy();
  const answer = requests.find(request => request.url.endsWith("/answer"));
  expect(answer?.headers.get("authorization")).toBe("Bearer fixture-token");
  expect(await answer?.json()).toMatchObject({conditionsRevision:1, waitingVersion:1, answer:selectedVersionId});
  expect(requests.filter(request => request.url.endsWith(`/tasks/${id}`)).length).toBeGreaterThanOrEqual(3);
});

test("sign-out clears a previously loaded private question", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(waiting)));
  const view = render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("你指的是哪個版本？")).toBeTruthy();
  auth.isAuthenticated = false;
  view.rerender(<ResearchTask taskId={id} />);
  await waitFor(() => expect(screen.queryByText("你指的是哪個版本？")).toBeNull());
  expect(screen.getByRole("button", {name:"登入查看委託"})).toBeTruthy();
});

test("a failed report read can be retried after the task is already complete", async () => {
  const completed: TaskView = {...waiting, viewVersion:4, status:"completed", stage:"報告完成", question:null, reportId};
  let reportReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin);
    if (url.pathname.endsWith(`/tasks/${id}`)) return Response.json(completed);
    if (url.pathname.endsWith(`/reports/${reportId}`)) {
      reportReads++;
      return reportReads === 1 ? new Response(null, {status:503})
        : Response.json({id:reportId, taskId:id, summary:"重新讀取成功", candidates:[]});
    }
    throw new Error(`Unexpected ${url}`);
  }));
  render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("報告暫時無法讀取，請重試。", {exact:false})).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name:"重新讀取"}));
  expect(await screen.findByText("重新讀取成功")).toBeTruthy();
  expect(reportReads).toBe(2);
});

test("completed report separates an unreviewed source excerpt from recommendations", async () => {
  const completed: TaskView = {...waiting, viewVersion:4, status:"completed", stage:"報告完成", question:null, reportId};
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin);
    if (url.pathname.endsWith(`/tasks/${id}`)) return Response.json(completed);
    if (url.pathname.endsWith(`/reports/${reportId}`)) return Response.json({
      id:reportId,taskId:id,summary:"依已覆核資料整理",candidates:[],unresolved:[],
      sourceObservations:[{id:"00000000-0000-4000-8000-000000000008",status:"ok",reviewStatus:"unreviewed",
        url:"https://www.drinks.com.tw/product.aspx?Id=1753",publisher:"來源商店",sourceCheckedOn:"2026-09-28",
        requestedUrl:"https://shop.us.glenfiddich.com/products/glenfiddich-12-year-old",
        observedAt:"2026-09-29T00:00:00Z",excerpt:"這是本次讀取的頁面文字",errorCode:null}],
    });
    throw new Error(`Unexpected ${url}`);
  }));
  render(<ResearchTask taskId={id} />);
  expect(await screen.findByText("這是本次讀取的頁面文字")).toBeTruthy();
  expect(screen.getByRole("heading", {name:"本次來源讀取（未覆核）"})).toBeTruthy();
  expect(screen.getByRole("link", {name:"https://www.drinks.com.tw/product.aspx?Id=1753"}).getAttribute("href")).toBe("https://www.drinks.com.tw/product.aspx?Id=1753");
  expect(screen.getByRole("link", {name:"原已覆核引用"}).getAttribute("href")).toBe("https://shop.us.glenfiddich.com/products/glenfiddich-12-year-old");
});
