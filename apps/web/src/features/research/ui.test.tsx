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
  user:{sub:"fixture-owner-a"},
  getAccessTokenSilently:vi.fn().mockResolvedValue("fixture-token"),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("@auth0/auth0-react", () => ({useAuth0:() => auth}));
vi.mock("next/navigation", () => ({useRouter:() => ({push, replace:vi.fn()})}));
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); auth.isAuthenticated = true; auth.user={sub:"fixture-owner-a"}; auth.getAccessTokenSilently.mockResolvedValue("fixture-token");});

const waiting: TaskView = {
  schemaVersion:1, taskId:id, threadId:"00000000-0000-4000-8000-000000000004",
  conditionsRevision:1, viewVersion:3, status:"needs_input", stage:"等待版本補充",
  question:{id:questionId, prompt:"你指的是哪個版本？", choices:[{id:"00000000-0000-4000-8000-000000000006",label:"12 年"},{id:selectedVersionId,label:"15 年"}], waitingVersion:1, expiresAt:"2026-10-06T00:00:00Z"},
  reportId:null, error:null, observedAt:"2026-09-29T00:00:00Z", activeRunId:null,
};

test("a completed report exposes explicit saving using the server-owned plan context",async()=>{
  const completed={...waiting,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async input=>{
    const path=String(input);
    if(path.endsWith("/conclusion-context")) return Response.json({schemaVersion:1,planId:id,taskId:id,reportId,conditionsRevision:1,currentConditionsRevision:1});
    if(path.endsWith("/comparison")) return new Response(null,{status:404});
    return path.includes(`/tasks/${id}`) ? Response.json(completed) : Response.json({id:reportId,taskId:id,summary:"已完成報告",candidates:[]});
  }));
  render(<ResearchTask taskId={id}/>);
  expect(await screen.findByRole("button",{name:"保存探索結論"})).toBeTruthy();
  expect(screen.getByLabelText("這次沒有適合的")).toBeTruthy();
});

test("completed candidates expose independent favorite and tasting feedback",async()=>{
  const completed={...waiting,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async input=>{
    const path=String(input);
    if(path.includes("/library/feedback/"))return Response.json({code:"NOT_FOUND"},{status:404});
    if(path.endsWith("/conclusion-context"))return Response.json({schemaVersion:1,planId:id,taskId:id,reportId,conditionsRevision:1,currentConditionsRevision:1});
    if(path.endsWith("/comparison"))return new Response(null,{status:404});
    return path.includes(`/tasks/${id}`) ? Response.json(completed) : Response.json({id:reportId,taskId:id,summary:"完成",candidates:[{itemId:id,bottleVersionId:selectedVersionId,name:"合成候選",reason:"來源理由",prices:[],claims:[]}]});
  }));
  render(<ResearchTask taskId={id}/>);
  expect(await screen.findByLabelText("想探索（收藏）")).toBeTruthy();
  expect(screen.getByLabelText("品飲感受")).toBeTruthy();
});

test("reopening a proposal question restores original clues and unconfirmed taste mapping",async()=>{
  vi.stubGlobal("fetch",vi.fn(async input=>{
    if(String(input).endsWith("/preference-proposal")) return Response.json({schemaVersion:4,taskId:id,planId:id,questionId,conditionsRevision:1,waitingVersion:1,sourceText:"我喜歡水果甜點",proposal:{summary:"原文只是線索",intent:{mode:"style_options",smoke_comparison:false},preferences:[{description:"可能喜歡果香",intent:"prefer",source_quote:"喜歡水果甜點",source_kind:"food_clue",certainty:"inferred",strength:"soft",mapping:{feature_key:"果香",reference:{release_id:id,item_id:id},evidence_ids:[id]}}],budget:null}});
    return Response.json(waiting);
  }));
  render(<ResearchTask taskId={id}/>);
  expect(await screen.findByText("我喜歡水果甜點")).toBeTruthy();
  expect(screen.getByText("飲食線索；偏好仍待確認")).toBeTruthy();
});

test("reopening a completed V4 task loads its sourced comparison independently of the legacy summary",async()=>{
  const completed={...waiting,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async(input)=>{
    const path=String(input);
    if(path.endsWith("/comparison")) return Response.json({schemaVersion:4,reportId,taskId:id,conditionsRevision:1,catalogReleaseId:null,evaluatedOn:"2026-09-30",comparison:{schemaVersion:4,intent:{mode:"style_options",smoke_comparison:false},candidates:[],unresolved:["目前起點的煙燻強度沒有覆核資料。"],unlistedName:null},items:[]});
    return path.includes(`/tasks/${id}`) ? Response.json(completed) : Response.json({id:reportId,taskId:id,summary:"已保存的摘要",candidates:[]});
  }));
  render(<ResearchTask taskId={id}/>);
  expect(await screen.findByText("已保存的摘要")).toBeTruthy();
  expect(await screen.findByText("目前起點的煙燻強度沒有覆核資料。")).toBeTruthy();
});

test("switching authenticated subjects immediately hides the previous owner's completed report",async()=>{
  const completed={...waiting,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async(input)=>{
    if(auth.user.sub!=="fixture-owner-a") return new Response(null,{status:404});
    return String(input).includes(`/tasks/${id}`) ? Response.json(completed)
      : Response.json({id:reportId,taskId:id,summary:"第一帳號私人報告",candidates:[]});
  }));
  const view=render(<ResearchTask taskId={id} />);
  await screen.findByText("第一帳號私人報告");
  auth.user={sub:"fixture-owner-b"};
  view.rerender(<ResearchTask taskId={id} />);
  expect(screen.queryByText("第一帳號私人報告")).toBeNull();
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取委託");
});

test("switching authenticated subjects removes unfinished work and the previous private form",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>Response.json(auth.user.sub==="fixture-owner-a" ? [waiting] : [])));
  const view=render(<ResearchStart />);
  await screen.findByRole("link",{name:"繼續上次探索"});
  fireEvent.change(screen.getByLabelText("想探索什麼風味？"),{target:{value:"第一帳號私人描述"}});
  auth.user={sub:"fixture-owner-b"};
  view.rerender(<ResearchStart />);
  expect(screen.queryByRole("link",{name:"繼續上次探索"})).toBeNull();
  expect(screen.queryByDisplayValue("第一帳號私人描述")).toBeNull();
});

test("a plan creation returning after subject change never starts or navigates the old owner's research",async()=>{
  let complete!:(value:Response)=>void;
  const fetch=vi.fn(async(input)=>{
    if(String(input).endsWith("/tasks")) return Response.json([]);
    if(String(input).endsWith("/plans")) return new Promise<Response>(resolve=>{complete=resolve;});
    throw new Error("Old research must not start");
  });
  vi.stubGlobal("fetch",fetch);
  const view=render(<ResearchStart />);
  fireEvent.change(screen.getByLabelText("想探索什麼風味？"),{target:{value:"果香"}});
  fireEvent.click(screen.getByRole("button",{name:"開始探索"}));
  await waitFor(()=>expect(complete).toBeTypeOf("function"));
  auth.user={sub:"fixture-owner-b"};
  view.rerender(<ResearchStart />);
  complete(Response.json({id,conditionsRevision:1}));
  await new Promise(resolve=>setTimeout(resolve,0));
  expect(fetch.mock.calls.some(call=>String(call[0]).endsWith("/agent"))).toBe(false);
  expect(push).not.toHaveBeenCalled();
});

test("a reopened completed report states its original task revision", async () => {
  const completed:TaskView={...waiting,conditionsRevision:1,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async(input)=>String(input).includes(`/tasks/${id}`)
    ? Response.json(completed)
    : Response.json({id:reportId,taskId:id,summary:"原條件的歷史報告",candidates:[]})));
  render(<ResearchTask taskId={id} />);
  await screen.findByText("原條件的歷史報告");
  expect(screen.getByText("此報告採用條件版本 1；修改條件後需另開研究。")).toBeTruthy();
});

test("changing task routes hides the old report before the next task responds",async()=>{
  const nextId="00000000-0000-4000-8000-000000000009";
  const completed={...waiting,status:"completed",question:null,reportId,stage:"完成"};
  vi.stubGlobal("fetch",vi.fn(async(input)=>{
    if(String(input).includes(nextId)) return new Promise<Response>(()=>{});
    return String(input).includes(`/tasks/${id}`) ? Response.json(completed)
      : Response.json({id:reportId,taskId:id,summary:"上一任務私人報告",candidates:[]});
  }));
  const view=render(<ResearchTask taskId={id} />);
  await screen.findByText("上一任務私人報告");
  view.rerender(<ResearchTask taskId={nextId} />);
  expect(screen.queryByText("上一任務私人報告")).toBeNull();
});

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
  expect(await requests.find(request => request.url.endsWith("/agent"))?.json()).toMatchObject({forwardedProps:{type:"start_v4", planId:id, conditionsRevision:1,input:{phase:"proposal",sourceText:"果香"}}});
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

test("unfinished task read failures remain visible and retry without creating a plan", async () => {
  let reads = 0;
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin);
    expect(url.pathname).toBe("/api/v1/tasks");
    reads++;
    return reads === 1 ? new Response(null, {status:503}) : Response.json([waiting]);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ResearchStart />);
  expect((await screen.findByRole("alert")).textContent).toContain("暫時無法讀取未完成的探索");
  fireEvent.click(screen.getByRole("button", {name:"重新讀取探索"}));
  expect(await screen.findByRole("link", {name:"繼續上次探索"})).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(reads).toBe(2);
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
