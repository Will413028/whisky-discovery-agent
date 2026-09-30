"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { safeReturnTo } from "../identity";
import { observeTask } from "./observe";
import { answerQuestion, createPlan, listOpenTasks, readReport, readTask, startResearch, type ReportView } from "./client";
import type { TaskView } from "./state";

function configured() {
  return Boolean(process.env.NEXT_PUBLIC_AUTH0_DOMAIN && process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID && process.env.NEXT_PUBLIC_AUTH0_AUDIENCE);
}

function requiredToken(value: string | undefined): string {
  if (!value) throw new Error("AUTH_REQUIRED");
  return value;
}

export function ResearchStartEntry() {
  if (!configured()) return <p>帳號功能準備中。</p>;
  return <ResearchStart />;
}

export function ResearchTaskEntry({taskId}: {taskId:string}) {
  if (!configured()) return <p>帳號功能準備中。</p>;
  return <ResearchTask taskId={taskId} />;
}

function usePrivateLogin() {
  const auth = useAuth0();
  const [loginError, setLoginError] = useState(false);
  const login = () => void auth.loginWithRedirect({appState:{returnTo:safeReturnTo(window.location.href, window.location.origin)}})
    .catch(() => setLoginError(true));
  return {auth, login, loginError};
}

export function ResearchStart() {
  const router = useRouter();
  const {auth, login, loginError} = usePrivateLogin();
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState<{planKey:string; startKey:string; threadId:string; runId:string; plan?:{id:string;conditionsRevision:number}}>();
  const [openTasks, setOpenTasks] = useState<TaskView[]>([]);
  const [tasksError, setTasksError] = useState(false);
  const [tasksRefresh, setTasksRefresh] = useState(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  useEffect(() => {
    if (!isAuthenticated) {setOpenTasks([]); setTasksError(false); return;}
    let live = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = requiredToken(await getAccessTokenSilently());
        const tasks = await listOpenTasks(token, controller.signal);
        if (live) {setOpenTasks(tasks); setTasksError(false);}
      } catch {if (live) setTasksError(true);}
    })();
    return () => {live = false; controller.abort();};
  }, [isAuthenticated, getAccessTokenSilently, tasksRefresh]);
  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!auth.isAuthenticated) return <><button onClick={login}>登入並開始探索</button>{loginError && <p role="alert">暫時無法登入，請重試。</p>}</>;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !goal.trim()) return;
    const current = attempt ?? {planKey:crypto.randomUUID(), startKey:crypto.randomUUID(), threadId:crypto.randomUUID(), runId:crypto.randomUUID()};
    setAttempt(current);
    setBusy(true);
    setError(false);
    void (async () => {
      try {
        const token = requiredToken(await auth.getAccessTokenSilently());
        const plan = current.plan ?? await createPlan(token, current.planKey, goal.trim(), budget ? budget : null);
        current.plan = plan;
        const task = await startResearch(token, plan, current.startKey, current.threadId, current.runId);
        router.push(`/research/${task.taskId}`);
      } catch {
        setError(true);
      } finally {
        setBusy(false);
      }
    })();
  };
  return <><form onSubmit={submit}>
    <label>想探索什麼風味？<input required maxLength={2000} value={goal} onChange={event => {setGoal(event.target.value); setAttempt(undefined);}} placeholder="例如：帶果香、適合第一次嘗試" /></label>
    <label>預算上限（新台幣，可留空）<input type="number" min="1" step="0.01" value={budget} onChange={event => {setBudget(event.target.value); setAttempt(undefined);}} /></label>
    <button type="submit" disabled={busy}>{busy ? "建立委託中…" : "開始探索"}</button>
    {error && <p role="alert">委託暫時無法確認；重試會使用同一筆指令。</p>}
  </form>{tasksError && <p role="alert">暫時無法讀取未完成的探索。
    <button type="button" onClick={() => setTasksRefresh(value => value + 1)}>重新讀取探索</button>
  </p>}{openTasks.length > 0 && <section><h2>未完成的探索</h2>
    {openTasks.map(task => <p key={task.taskId}><a href={`/research/${task.taskId}`}>繼續上次探索</a> — {task.stage}</p>)}
  </section>}</>;
}

export function ResearchTask({taskId}: {taskId:string}) {
  const {auth, login, loginError} = usePrivateLogin();
  const [task, setTask] = useState<TaskView | null>(null);
  const [report, setReport] = useState<ReportView | null>(null);
  const [selected, setSelected] = useState("");
  const [answerAttempt, setAnswerAttempt] = useState<{questionId:string;answer:string;key:string;pending:boolean} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  const activeRunId = task?.activeRunId;

  useEffect(() => {
    if (!isAuthenticated || !task || !activeRunId || !["acceptance_pending", "queued", "researching"].includes(task.status)) return;
    let live = true;
    const controller = new AbortController();
    void observeTask({
      initial:{taskId:task.taskId, threadId:task.threadId, conditionsRevision:task.conditionsRevision,
        connection:0, view:task, connected:false},
      runId:activeRunId,
      token:async () => requiredToken(await getAccessTokenSilently()),
      onState:state => {if (live && state.view) setTask(previous => previous && previous.viewVersion >= state.view!.viewVersion ? previous : state.view);},
      signal:controller.signal, fetch:window.fetch.bind(window), random:Math.random,
      sleep:(milliseconds, signal) => new Promise(resolve => {
        const timer = window.setTimeout(resolve, milliseconds);
        signal.addEventListener("abort", () => {window.clearTimeout(timer); resolve();}, {once:true});
      }),
    }).catch(() => {if (live) setError("即時觀察暫時中斷，正在讀取保存狀態。");});
    return () => {live = false; controller.abort();};
  }, [isAuthenticated, activeRunId, task?.status, task?.taskId, getAccessTokenSilently]);

  useEffect(() => {
    if (!isAuthenticated) {setTask(null); setReport(null); setAnswerAttempt(null); return;}
    let live = true;
    const controller = new AbortController();
    const load = async () => {
      try {
        const token = requiredToken(await getAccessTokenSilently());
        if (!live) return;
        const next = await readTask(taskId, token, controller.signal);
        if (!live) return;
        setTask(previous => previous && previous.viewVersion > next.viewVersion ? previous : next);
        setError(null);
      } catch (cause) {
        if (live) setError(cause instanceof Error && cause.message === "AUTH_REQUIRED" ? "登入已過期，請重新登入。" : "暫時無法讀取委託，請重試。");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 2500);
    return () => {live = false; controller.abort(); window.clearInterval(timer);};
  }, [isAuthenticated, getAccessTokenSilently, taskId, refresh]);

  useEffect(() => {
    if (!isAuthenticated || !task || task.status !== "completed" || !task.reportId) {setReport(null); return;}
    let live = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = requiredToken(await getAccessTokenSilently());
        if (!live) return;
        const next = await readReport(task, token, controller.signal);
        if (live) setReport(next);
      } catch {if (live) setError("報告暫時無法讀取，請重試。");}
    })();
    return () => {live = false; controller.abort();};
  }, [isAuthenticated, getAccessTokenSilently, task?.reportId, task?.status, task?.taskId, refresh]);

  const submitAnswer = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!task?.question || busy) return;
    const previous = answerAttempt?.questionId === task.question.id ? answerAttempt : null;
    const answer = previous?.answer ?? selected;
    if (!task.question.choices.some(choice => choice.id === answer)) return;
    const current = previous ?? {questionId:task.question.id, answer, key:crypto.randomUUID(), pending:false};
    setAnswerAttempt(current);
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        const token = requiredToken(await getAccessTokenSilently());
        const result = await answerQuestion(task, current.answer, current.key, token);
        setAnswerAttempt({...current, pending:result.acceptance === "acceptance_pending"});
        setRefresh(value => value + 1);
      } catch {setError("答覆暫時無法確認；請用同一答覆重試。");}
      finally {setBusy(false);}
    })();
  };

  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!isAuthenticated) return <><button onClick={login}>登入查看委託</button>{loginError && <p role="alert">暫時無法登入，請重試。</p>}</>;
  return <section aria-live="polite">
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh(value => value + 1)}>重新讀取</button></p>}
    {!task && <p>讀取委託中…</p>}
    {task && <>
      <p>狀態：{task.stage}</p>
      {task.status === "needs_input" && task.question && <form onSubmit={submitAnswer}>
        <h2>需要補充資料</h2>
        <p>{task.question.prompt}</p>
        <fieldset disabled={busy || Boolean(answerAttempt?.pending)}>
          <legend>請選擇版本</legend>
          {task.question.choices.map(choice => <label key={choice.id} className="choice"><input type="radio" name="answer" value={choice.id}
            checked={(answerAttempt?.questionId === task.question?.id ? answerAttempt?.answer : selected) === choice.id}
            onChange={() => setSelected(choice.id)} />{choice.label}</label>)}
        </fieldset>
        <p>請於 {new Date(task.question.expiresAt).toLocaleString("zh-TW")} 前回覆。</p>
        <button type="submit" disabled={busy || (!selected && !answerAttempt)}>{busy ? "送出中…" : answerAttempt ? "重送同一答覆" : "送出答覆"}</button>
        {answerAttempt?.pending && <p>答覆已保存，等待工作流程確認。必要時可重送同一答覆。</p>}
      </form>}
      {task.status === "completed" && (report ? <article><h2>探索報告</h2><p>{report.summary}</p>
        {report.clarifiedBottle && <p>已補充版本：{report.clarifiedBottle.name}{!report.clarifiedBottle.reviewedInRelease && "（目前資料未覆核）"}</p>}
        {report.unresolved?.map(value => <p key={value}>待確認：{value}</p>)}
        {report.candidates.map(candidate => <section key={candidate.itemId}><h3>{candidate.name}</h3><p>{candidate.reason}</p>
          {candidate.prices.map(price => <p key={price.id}>參考價格：{price.amount ?? "未提供"} {price.currency}／{price.volumeMl ?? "?"} ml，{price.market}，查核日期 {price.checkedOn ?? "未提供"}</p>)}
          {candidate.claims.flatMap(claim => claim.sources).map(source => <p key={source.evidenceId}>來源：<a href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher ?? source.url}</a>（{source.checkedOn}）</p>)}
        </section>)}
        {Boolean(report.sourceObservations?.length) && <section><h3>本次來源讀取（未覆核）</h3>
          <p>以下是本次讀取的頁面觀察，尚未納入已覆核事實、推薦或預算判定。</p>
          {report.sourceObservations.map(observation => <div key={observation.id}>
            <p>本次讀取：<a href={observation.url} target="_blank" rel="noopener noreferrer">{observation.url}</a>，讀取時間 {new Date(observation.observedAt).toLocaleString("zh-TW")}；原來源查核日 {observation.sourceCheckedOn}</p>
            {observation.requestedUrl !== observation.url && <p>原已覆核來源（{observation.publisher ?? "來源未標示"}）：<a href={observation.requestedUrl} target="_blank" rel="noopener noreferrer">原已覆核引用</a></p>}
            {observation.excerpt && <blockquote>{observation.excerpt}</blockquote>}
            {observation.status === "unavailable" && <p>這次無法讀取：{observation.errorCode}</p>}
          </div>)}
        </section>}
      </article> : <p>讀取報告中…</p>)}
      {task.status === "failed" && <p role="alert">研究未完成：{task.error?.message}</p>}
      {task.status === "cancelled" && <p>委託已取消。</p>}
      {task.status === "superseded" && <p>委託條件已更新。</p>}
    </>}
  </section>;
}
