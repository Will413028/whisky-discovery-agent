"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { safeReturnTo } from "../identity";
import { observeTask } from "./observe";
import { answerQuestion, createPlan, listOpenTasks, readReport, readTask, startResearchV4, type ReportView, type ResearchInputV4 } from "./client";
import {readPreferenceProposal,type PreferenceProposalView} from "./proposal-client";
import {PreferenceProposalCard} from "./proposal-ui";
import type { TaskView } from "./state";
import {readComparison, type ComparisonReportView} from "./comparison-client";
import {ComparisonReport} from "./comparison-ui";
import {ApplyLongTermPreferences,BottleFeedbackEditor,ReportConclusion,type LongTermPreference} from "../library";

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
  const auth = useAuth0();
  return <ResearchStartSession key={JSON.stringify([auth.isAuthenticated,auth.user?.sub])} />;
}

function usePrivateLifetime() {
  const generation=useRef(0);
  useEffect(()=>{generation.current++; return ()=>{generation.current++;};},[]);
  return generation;
}

function ResearchStartSession() {
  const router = useRouter();
  const {auth, login, loginError} = usePrivateLogin();
  const life=usePrivateLifetime();
  const [goal, setGoal] = useState("");
  const [entry,setEntry]=useState<"beginner" | "expert">("beginner");
  const [origin,setOrigin]=useState("");
  const [mode,setMode]=useState<"style_options" | "similar" | "small_step" | "contrast">("similar");
  const [keepFeature,setKeepFeature]=useState("");
  const [exploreFeature,setExploreFeature]=useState("");
  const [originFeature,setOriginFeature]=useState("");
  const [candidateFeature,setCandidateFeature]=useState("");
  const [budget, setBudget] = useState("");
  const [savedPreferences,setSavedPreferences]=useState<LongTermPreference[]>([]);
  const [preferenceConflict,setPreferenceConflict]=useState<string|null>(null);
  const preferenceToken=useCallback(async()=>requiredToken(await auth.getAccessTokenSilently()),[auth.getAccessTokenSilently]);
  const selectPreferences=useCallback((values:LongTermPreference[])=>{setSavedPreferences(values);setAttempt(undefined);setPreferenceConflict(null);},[]);
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
    if (busy || !(entry === "beginner" ? goal.trim() : origin.trim()) || (entry==="expert" && mode==="small_step" && (!keepFeature.trim() || !exploreFeature.trim())) || (entry==="expert" && mode==="contrast" && (!originFeature.trim() || !candidateFeature.trim()))) return;
    setPreferenceConflict(null);
    const retained=entry==="expert" && keepFeature.trim() ? savedPreferences.find(value=>value.description===keepFeature.trim()) : undefined;
    if(retained?.intent==="avoid"){
      setPreferenceConflict("已選排斥偏好與保留特徵衝突；請取消其中一項後再開始探索。");return;
    }
    if(savedPreferences.length+(entry==="expert" && keepFeature.trim() && !retained ? 1 : 0)>64){
      setPreferenceConflict("一次探索最多 64 項偏好，請減少已選項目。");return;
    }
    const generation=life.current;
    const current = attempt ?? {planKey:crypto.randomUUID(), startKey:crypto.randomUUID(), threadId:crypto.randomUUID(), runId:crypto.randomUUID()};
    setAttempt(current);
    setBusy(true);
    setError(false);
    void (async () => {
      try {
        const token = requiredToken(await auth.getAccessTokenSilently());
        if(generation!==life.current) return;
        const preferences=savedPreferences.map(value=>({description:value.description,intent:value.intent,certainty:"user_stated" as const,strength:value.strength}));
        if(entry==="expert" && keepFeature.trim()){
          const existing=preferences.findIndex(value=>value.description===keepFeature.trim());
          if(existing!==-1)preferences.splice(existing,1);
        }
        const plan = current.plan ?? await createPlan(token, current.planKey, entry === "beginner" ? goal.trim() : `從「${origin.trim()}」探索`, budget ? budget : null, [...preferences,...(entry==="expert" && keepFeature.trim() ? [{description:keepFeature.trim(),intent:"keep" as const,certainty:"user_stated" as const,strength:retained?.strength ?? "soft" as const}] : [])]);
        if(generation!==life.current) return;
        current.plan = plan;
        const input:ResearchInputV4={schemaVersion:4,phase:entry === "beginner" ? "proposal" : "research",sourceText:entry === "beginner" ? goal : null,intent:{mode:entry === "beginner" ? "style_options" : mode,origin_query:entry === "expert" ? origin.trim() : null,smoke_comparison:false,explore_feature:entry==="expert" && mode==="small_step" ? exploreFeature.trim() : null,contrast:entry==="expert" && mode==="contrast" ? {axis:"flavor_description",origin_feature:originFeature.trim(),candidate_feature:candidateFeature.trim()} : null}};
        const task = await startResearchV4(token, plan, current.startKey, current.threadId, current.runId,input);
        if(generation===life.current) router.push(`/research/${task.taskId}`);
      } catch {
        if(generation===life.current) setError(true);
      } finally {
        if(generation===life.current) setBusy(false);
      }
    })();
  };
  return <><p><a href="/plans">查看我的探索計畫</a></p><form onSubmit={submit}>
    <fieldset disabled={busy}><legend>從哪裡開始？</legend>
    <label><input type="radio" name="entry" checked={entry==="beginner"} onChange={()=>{setEntry("beginner");setAttempt(undefined);}}/>不知道自己喜歡什麼</label>
    <label><input type="radio" name="entry" checked={entry==="expert"} onChange={()=>{setEntry("expert");setAttempt(undefined);}}/>我有喜歡的酒款</label>
    {entry === "beginner" ? <>
    <label>想探索什麼風味？<input required maxLength={2000} value={goal} onChange={event => {setGoal(event.target.value); setAttempt(undefined);}} placeholder="例如：帶果香、適合第一次嘗試" /></label>
    <p>飲食與風味描述會先整理成待確認線索。</p></> : <>
    <label>喜歡的酒款名稱<input required maxLength={1000} value={origin} onChange={event=>{setOrigin(event.target.value);setAttempt(undefined);}} placeholder="例如：格蘭菲迪 12 年"/></label>
    <label>探索方向<select value={mode} onChange={event=>{setMode(event.target.value as typeof mode);setAttempt(undefined);}}><option value="similar">找相似選擇</option><option value="small_step">保留一個特徵，向外探索一步</option><option value="contrast">比較兩種風味描述</option><option value="style_options">看看其他風格</option></select></label>
    <label>想保留的風味標籤<input required={mode==="small_step"} maxLength={1000} value={keepFeature} onChange={event=>{setKeepFeature(event.target.value);setAttempt(undefined);}} placeholder="例如：果香（可留空）"/></label>
    {mode==="small_step" && <label>想嘗試的風味標籤<input required maxLength={1000} value={exploreFeature} onChange={event=>{setExploreFeature(event.target.value);setAttempt(undefined);}} placeholder="例如：蜂蜜"/></label>}
    {mode==="contrast" && <><label>起點風味描述<input required maxLength={1000} value={originFeature} onChange={event=>{setOriginFeature(event.target.value);setAttempt(undefined);}} placeholder="例如：蜂蜜"/></label><label>想對比的風味描述<input required maxLength={1000} value={candidateFeature} onChange={event=>{setCandidateFeature(event.target.value);setAttempt(undefined);}} placeholder="例如：葡萄乾"/></label><p>比較只引用兩端已覆核描述，資料不足時會明示；不推算煙燻強弱。</p></>}
    <p>研究會先請你確認已覆核的版本；未收錄的酒款會明示資料不足。</p></>}
    <label>預算上限（新台幣，可留空）<input type="number" min="1" step="0.01" value={budget} onChange={event => {setBudget(event.target.value); setAttempt(undefined);}} /></label>
    <ApplyLongTermPreferences token={preferenceToken} onChange={selectPreferences} disabled={busy}/>
    <button type="submit" disabled={busy}>{busy ? "建立委託中…" : "開始探索"}</button>
    </fieldset>
    {error && <p role="alert">委託暫時無法確認；重試會使用同一筆指令。</p>}
    {preferenceConflict && <p role="alert">{preferenceConflict}</p>}
  </form>{tasksError && <p role="alert">暫時無法讀取未完成的探索。
    <button type="button" onClick={() => setTasksRefresh(value => value + 1)}>重新讀取探索</button>
  </p>}{openTasks.length > 0 && <section><h2>未完成的探索</h2>
    {openTasks.map(task => <p key={task.taskId}><a href={`/research/${task.taskId}`}>繼續上次探索</a> — {task.stage}</p>)}
  </section>}</>;
}

export function ResearchTask({taskId}: {taskId:string}) {
  const auth = useAuth0();
  return <ResearchTaskSession key={JSON.stringify([auth.isAuthenticated,auth.user?.sub,taskId])} taskId={taskId} />;
}

function ResearchTaskSession({taskId}: {taskId:string}) {
  const {auth, login, loginError} = usePrivateLogin();
  const life=usePrivateLifetime();
  const [task, setTask] = useState<TaskView | null>(null);
  const [report, setReport] = useState<ReportView | null>(null);
  const [comparison, setComparison] = useState<ComparisonReportView | null>(null);
  const [comparisonError, setComparisonError] = useState(false);
  const [proposal,setProposal]=useState<PreferenceProposalView | null>(null);
  const [proposalError,setProposalError]=useState(false);
  const [selected, setSelected] = useState("");
  const [answerAttempt, setAnswerAttempt] = useState<{questionId:string;answer:string;key:string;pending:boolean} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  const activeRunId = task?.activeRunId;
  const conclusionToken=useCallback(async()=>requiredToken(await getAccessTokenSilently()),[getAccessTokenSilently]);

  useEffect(()=>{
    setProposal(null);setProposalError(false);
    if(!isAuthenticated || task?.status!=="needs_input" || !task.question) return;
    let live=true;
    const controller=new AbortController();
    void (async()=>{
      try {
        const token=requiredToken(await getAccessTokenSilently());
        if(!live) return;
        const draft=await readPreferenceProposal(task,token,controller.signal);
        if(live) setProposal(draft);
      } catch {if(live) setProposalError(true);}
    })();
    return ()=>{live=false;controller.abort();};
  },[isAuthenticated,getAccessTokenSilently,task?.taskId,task?.status,task?.conditionsRevision,task?.question?.id,task?.question?.waitingVersion,refresh]);

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

  useEffect(() => {
    setComparison(null);
    setComparisonError(false);
    if (!isAuthenticated || task?.status !== "completed" || !task.reportId) return;
    let live=true;
    const controller=new AbortController();
    void (async()=>{
      try {
        const token=requiredToken(await getAccessTokenSilently());
        if (!live) return;
        const next=await readComparison(task.reportId!,task.taskId,token,controller.signal);
        if(live) setComparison(next);
      } catch {if(live) setComparisonError(true);}
    })();
    return ()=>{live=false;controller.abort();};
  }, [isAuthenticated,getAccessTokenSilently,task?.reportId,task?.status,task?.taskId,refresh]);

  const submitAnswer = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!task?.question || busy) return;
    const generation=life.current;
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
        if(generation!==life.current) return;
        const result = await answerQuestion(task, current.answer, current.key, token);
        if(generation!==life.current) return;
        setAnswerAttempt({...current, pending:result.acceptance === "acceptance_pending"});
        setRefresh(value => value + 1);
      } catch {if(generation===life.current)setError("答覆暫時無法確認；請用同一答覆重試。");}
      finally {if(generation===life.current)setBusy(false);}
    })();
  };

  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!isAuthenticated) return <><button onClick={login}>登入查看委託</button>{loginError && <p role="alert">暫時無法登入，請重試。</p>}</>;
  return <section aria-live="polite">
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh(value => value + 1)}>重新讀取</button></p>}
    {!task && <p>讀取委託中…</p>}
    {task && <>
      <p>狀態：{task.stage}</p>
      {proposal && proposal.questionId===task.question?.id && proposal.conditionsRevision===task.conditionsRevision && task.status==="needs_input" && <PreferenceProposalCard view={proposal}/>}
      {proposalError && <p role="alert">偏好草稿暫時無法讀取。<button type="button" onClick={()=>setRefresh(value=>value+1)}>重新讀取草稿</button></p>}
      {task.status === "needs_input" && task.question && <form onSubmit={submitAnswer}>
        <h2>需要補充資料</h2>
        <p>{task.question.prompt}</p>
        <fieldset disabled={busy || Boolean(answerAttempt?.pending)}>
          <legend>請選擇答覆</legend>
          {task.question.choices.map(choice => <label key={choice.id} className="choice"><input type="radio" name="answer" value={choice.id}
            checked={(answerAttempt?.questionId === task.question?.id ? answerAttempt?.answer : selected) === choice.id}
            onChange={() => setSelected(choice.id)} />{choice.label}</label>)}
        </fieldset>
        <p>請於 {new Date(task.question.expiresAt).toLocaleString("zh-TW")} 前回覆。</p>
        <button type="submit" disabled={busy || (!selected && !answerAttempt)}>{busy ? "送出中…" : answerAttempt ? "重送同一答覆" : "送出答覆"}</button>
        {answerAttempt?.pending && <p>答覆已保存，等待工作流程確認。必要時可重送同一答覆。</p>}
      </form>}
      {task.status === "completed" && (report ? <article><h2>探索報告</h2><p>此報告採用條件版本 {task.conditionsRevision}；修改條件後需另開研究。</p><p>{report.summary}</p>
        {report.clarifiedBottle && <p>已補充版本：{report.clarifiedBottle.name}{!report.clarifiedBottle.reviewedInRelease && "（目前資料未覆核）"}</p>}
        {report.unresolved?.map(value => <p key={value}>待確認：{value}</p>)}
        {comparison?.reportId === report.id && <ComparisonReport view={comparison}/>}
        {comparisonError && <p>風味比較暫時無法讀取。<button type="button" onClick={()=>setRefresh(value=>value+1)}>重試比較</button></p>}
        {report.candidates.map(candidate => <section key={candidate.itemId}><h3>{candidate.name}</h3><p>{candidate.reason}</p>
          {candidate.prices.map(price => <p key={price.id}>參考價格：{price.amount ?? "未提供"} {price.currency}／{price.volumeMl ?? "?"} ml，{price.market}，查核日期 {price.checkedOn ?? "未提供"}</p>)}
          {candidate.claims.flatMap(claim => claim.sources).map(source => <p key={source.evidenceId}>來源：<a href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher ?? source.url}</a>（{source.checkedOn}）</p>)}
          <BottleFeedbackEditor version={candidate.bottleVersionId} name={candidate.name} token={conclusionToken}/>
        </section>)}
        <ReportConclusion key={`${report.id}:${task.conditionsRevision}`} reportId={report.id} taskId={task.taskId} revision={task.conditionsRevision} candidates={report.candidates.map(candidate=>({versionId:candidate.bottleVersionId,name:candidate.name}))} getToken={conclusionToken}/>
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
