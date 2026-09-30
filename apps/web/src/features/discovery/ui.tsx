"use client";

import {useAuth0} from "@auth0/auth0-react";
import {useRouter} from "next/navigation";
import {useEffect, useRef, useState, type FormEvent} from "react";
import {safeReturnTo} from "../identity";
import {startResearchV4,ProposalPlanEditor,readActivePlanProposal,proposalIdentity,type ProposalPatch,type ResearchInputV4} from "../research";
import {RestartDirection,canReuseDirection} from "./restart-direction";
import type {RestartContext} from "./restart-client";
import {PreferenceEditor} from "./preference-editor";
import {preferencePatch,savedPreferences,selectProposal,hasAmbiguousPreferenceEdits,duplicatePreferenceDescriptions,type PreferenceDraft} from "./preference-draft";
import {PlanHistory} from "./history";
import {listPlans, patchPlan, readControl, readPlan, RequestRejected, type ControlView, type PatchRequest, type PlanView} from "./client";

type Attempt = {body:PatchRequest; receipt:ControlView | null};
type StartAttempt = {key:string; threadId:string; runId:string; plan:PlanView;input:ResearchInputV4;sourceTaskId?:string};

export function Plans() {
  const auth = useAuth0();
  const [items, setItems] = useState<PlanView[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const life = useRef(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  const subject = auth.user?.sub;
  const load = (next:string | null, generation:number, reset:boolean, signal?:AbortSignal) => {
    setBusy(true); setError(null);
    void (async () => {
      try {
        const token = await getAccessTokenSilently();
        if (generation !== life.current) return;
        if (!token) throw new Error("AUTH_REQUIRED");
        const page = await listPlans(token,next,signal);
        if (generation !== life.current) return;
        setItems(previous => [...new Map([...(reset ? [] : previous ?? []),...page.items].map(item => [item.id,item])).values()]);
        setCursor(page.nextCursor);
      } catch {if (generation === life.current) setError("暫時無法讀取探索計畫。");}
      finally {if (generation === life.current) setBusy(false);}
    })();
  };
  useEffect(() => {
    const generation = ++life.current;
    setItems(null); setCursor(null); setError(null); setBusy(false);
    if (!isAuthenticated) return;
    const controller = new AbortController();
    load(null,generation,true,controller.signal);
    return () => {life.current++; controller.abort();};
  }, [isAuthenticated,getAccessTokenSilently,subject]);
  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!isAuthenticated) return <><button onClick={() => void auth.loginWithRedirect({appState:{returnTo:safeReturnTo(window.location.href,window.location.origin)}}).catch(() => setError("暫時無法登入，請重試。"))}>登入查看探索計畫</button>{error && <p role="alert">{error}</p>}</>;
  return <section>
    {error && <p role="alert">{error}<button disabled={busy} onClick={() => load(cursor,life.current,items === null)}>重新讀取計畫</button></p>}
    {!items && !error && <p>讀取探索計畫中…</p>}
    {items?.length === 0 && <p>尚未有探索計畫。</p>}
    {items && items.length > 0 && <ul>{items.map(item => <li key={item.id}><a href={`/plans/${item.id}`}>{item.conditions.goal}</a> — 條件版本 {item.conditionsRevision}</li>)}</ul>}
    {cursor && !error && <button disabled={busy} onClick={() => load(cursor,life.current,false)}>讀取更多計畫</button>}
    <a href="/research">開始新的探索</a>
  </section>;
}

function configured() {
  return Boolean(process.env.NEXT_PUBLIC_AUTH0_DOMAIN && process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID && process.env.NEXT_PUBLIC_AUTH0_AUDIENCE);
}

export function PlansEntry() {
  return configured() ? <Plans /> : <p>帳號功能準備中。</p>;
}

export function PlanDetailEntry({planId,proposalTaskId,restartTaskId}: {planId:string;proposalTaskId?:string;restartTaskId?:string}) {
  if (!configured()) return <p>帳號功能準備中。</p>;
  return <PlanDetail planId={planId} proposalTaskId={proposalTaskId} restartTaskId={restartTaskId} />;
}

export function PlanDetail({planId,proposalTaskId,restartTaskId}: {planId:string;proposalTaskId?:string;restartTaskId?:string}) {
  const auth = useAuth0();
  const router = useRouter();
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [goal, setGoal] = useState("");
  const [budgetDraft, setBudgetDraft] = useState<{value:string;source:"saved"|"manual"|"proposal"}>({value:"",source:"saved"});
  const budget=budgetDraft.value;
  const proposalIdentityRef=useRef<string|null>(null);
  const [preferenceDraft,setPreferenceDraft]=useState<PreferenceDraft[]>([]);
  const ambiguousPreferences=hasAmbiguousPreferenceEdits(preferenceDraft);
  const editedPreferences=preferencePatch(plan?.conditions.preferences ?? [],preferenceDraft);
  const proposalPatch=editedPreferences.upsert_preferences.length || editedPreferences.remove_preferences.length ? editedPreferences : null;
  const hasProposal=preferenceDraft.some(row=>row.source==="proposal" && !row.removed);
  const acceptProposalPatch=(patch:ProposalPatch|null)=>setPreferenceDraft(previous=>selectProposal(previous,plan?.conditions.preferences ?? [],patch?.upsert_preferences ?? []));
  const [loadError, setLoadError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [rejected, setRejected] = useState(false);
  const [startAttempt, setStartAttempt] = useState<StartAttempt | null>(null);
  const [restartSelection,setRestartSelection]=useState<RestartContext|null|undefined>(undefined);
  const life = useRef(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  const subject = auth.user?.sub;

  const acceptPlan = (value:PlanView) => {
    setPreferenceDraft(savedPreferences(value.conditions.preferences ?? []));
    setPlan(value); setGoal(value.conditions.goal); setBudgetDraft({value:value.conditions.budget_twd ?? "",source:"saved"});
  };

  const acceptProposalBudget=(value:string|null|undefined)=>{
    setBudgetDraft(previous=>value!==undefined
      ? {value:value ?? "",source:"proposal"}
      : previous.source==="proposal" ? {value:plan?.conditions.budget_twd ?? "",source:"saved"} : previous);
  };

  useEffect(() => {
    const generation = ++life.current;
    setPlan(null); setAttempt(null); setRejected(false); setStartAttempt(null); setError(null); setBusy(false); setLoadError(false);
    setRestartSelection(undefined);
    if (!isAuthenticated) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getAccessTokenSilently();
        if (generation !== life.current) return;
        if (!token) throw new Error("AUTH_REQUIRED");
        const value = await readPlan(planId, token, controller.signal);
        if (generation === life.current) acceptPlan(value);
      } catch {if (generation === life.current) setLoadError(true);}
    })();
    return () => {life.current++; controller.abort();};
  }, [planId, proposalTaskId,restartTaskId,isAuthenticated, getAccessTokenSilently, subject, refresh]);

  const confirm = (current:Attempt) => {
    const generation = life.current;
    setAttempt(current); setRejected(false); setBusy(true); setError(null);
    void (async () => {
      try {
        const token = await getAccessTokenSilently();
        if (generation !== life.current) return;
        if (!token) throw new Error("AUTH_REQUIRED");
        const receipt = current.receipt && current.receipt.status !== "pending"
          ? await readControl(current.receipt.id, token) : await patchPlan(planId, token, current.body);
        if (generation !== life.current) return;
        if (receipt.targetId !== planId || receipt.kind !== "plan.change_conditions") throw new Error("INVALID_RESPONSE");
        setAttempt({...current, receipt});
        if (receipt.status === "rejected") {
          setError("這次變更未套用，請重新讀取計畫。");
        } else if (receipt.status === "completed") {
          const next = await readPlan(planId, token);
          if (generation !== life.current) return;
          if (next.conditionsRevision <= current.body.expectedRevision) throw new Error("INVALID_RESPONSE");
          acceptPlan(next); setAttempt(null);
        }
      } catch (cause) {
        if (generation === life.current) {
          if (!current.receipt && cause instanceof RequestRejected) {
            setRejected(true); setError("變更未受理，請重新讀取計畫後調整。");
          } else setError("變更暫時無法確認；重試會使用同一筆指令。");
        }
      }
      finally {if (generation === life.current) setBusy(false);}
    })();
  };

  const submit = async (event:FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!plan || busy || attempt || startAttempt || ambiguousPreferences) return;
    if(proposalTaskId && (hasProposal || budgetDraft.source==="proposal")) {
      const generation=life.current;
      setBusy(true);
      try {
        const token=await getAccessTokenSilently();
        if(generation!==life.current) return;
        if(!token) throw new Error("AUTH_REQUIRED");
        const draft=await readActivePlanProposal(proposalTaskId,planId,plan.conditionsRevision,token);
        if(generation!==life.current) return;
        if(!draft || proposalIdentity(draft.view)!==proposalIdentityRef.current) {
          acceptProposalPatch(null);acceptProposalBudget(undefined);setError("此草稿已關閉，請重新確認目前條件。");return;
        }
      } catch {if(generation===life.current) setError("無法確認草稿是否有效，請重試。");return;}
      finally {if(generation===life.current) setBusy(false);}
    }
    const patch:PatchRequest["patch"] = proposalPatch ? {...proposalPatch} : {upsert_preferences:[], remove_preferences:[]};
    if (goal.trim() !== plan.conditions.goal) patch.goal = goal.trim();
    if (budget !== (plan.conditions.budget_twd ?? "")) patch.budget_twd = budget || null;
    if (!proposalPatch && !("goal" in patch) && !("budget_twd" in patch)) return;
    confirm({body:{key:crypto.randomUUID(), expectedRevision:plan.conditionsRevision, baseConditions:plan.conditions, patch}, receipt:null});
  };

  const start = () => {
    if (!plan || busy || attempt || (restartTaskId && (restartSelection===undefined || (restartSelection && !canReuseDirection(plan,restartSelection))))) return;
    const generation = life.current;
    const input:ResearchInputV4=restartSelection ? restartSelection.input : {schemaVersion:4,phase:"research",sourceText:null,intent:{mode:"style_options",origin_query:null,explore_feature:null,contrast:null,smoke_comparison:false}};
    const current = startAttempt ?? {key:crypto.randomUUID(),threadId:crypto.randomUUID(),runId:crypto.randomUUID(),plan,input,sourceTaskId:restartSelection?.taskId};
    setStartAttempt(current); setBusy(true); setError(null);
    void (async () => {
      try {
        const token = await getAccessTokenSilently();
        if (generation !== life.current) return;
        if (!token) throw new Error("AUTH_REQUIRED");
        const task = await startResearchV4(token,current.plan,current.key,current.threadId,current.runId,current.input,current.sourceTaskId);
        if (generation === life.current) router.push(`/research/${task.taskId}`);
      } catch {if (generation === life.current) setError("委託暫時無法確認；重試會使用同一筆指令。");}
      finally {if (generation === life.current) setBusy(false);}
    })();
  };

  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!isAuthenticated) return <><button onClick={() => void auth.loginWithRedirect({appState:{returnTo:safeReturnTo(window.location.href,window.location.origin)}}).catch(() => setError("暫時無法登入，請重試。"))}>登入查看探索計畫</button>{error && <p role="alert">{error}</p>}</>;
  const visible = plan?.id === planId ? plan : null;
  const dirty = Boolean(visible && (proposalPatch || goal.trim() !== visible.conditions.goal || budget !== (visible.conditions.budget_twd ?? "")));
  return <section>
    {loadError && <p role="alert">暫時無法讀取計畫。<button onClick={() => setRefresh(value => value + 1)}>重新讀取計畫</button></p>}
    {error && <p role="alert">{error}</p>}
    {!visible && !loadError && <p>讀取計畫中…</p>}
    {visible && <>
      <p>條件版本：{visible.conditionsRevision}</p>
      {restartTaskId && <RestartDirection key={JSON.stringify([visible.id,restartTaskId,subject])} plan={visible} taskId={restartTaskId} selected={restartSelection} disabled={busy || Boolean(attempt) || Boolean(startAttempt)} onChange={setRestartSelection}/>}
      <form onSubmit={submit}>
        {proposalTaskId && <ProposalPlanEditor taskId={proposalTaskId} planId={visible.id} revision={visible.conditionsRevision} disabled={busy || Boolean(attempt) || Boolean(startAttempt)} onChange={acceptProposalPatch} onBudgetChange={acceptProposalBudget} budgetSelected={budgetDraft.source==="proposal"} blockedFeatures={duplicatePreferenceDescriptions(preferenceDraft)} onIdentity={identity=>{proposalIdentityRef.current=identity;}}/>}
        <PreferenceEditor draft={preferenceDraft} onChange={setPreferenceDraft} disabled={busy || Boolean(attempt) || Boolean(startAttempt)}/>
        <fieldset disabled={busy || Boolean(attempt) || Boolean(startAttempt)}>
          <label>本次探索目標<input required maxLength={2000} value={goal} onChange={event => setGoal(event.target.value)} /></label>
          <label>本次預算上限（新台幣，可留空）<input type="number" min="0.01" step="0.01" value={budget} onChange={event => setBudgetDraft({value:event.target.value,source:"manual"})} /></label>
          <button type="submit" disabled={!dirty || ambiguousPreferences}>保存指定修改</button>
        </fieldset>
      </form>
      <p>已保存的偏好：{visible.conditions.preferences?.length ? visible.conditions.preferences.map(value => value.description).join("、") : "尚未指定"}</p>
      {attempt && <>
        {attempt.receipt && !["completed","rejected"].includes(attempt.receipt.status) && <p>變更等待確認；尚未建立新研究。</p>}
        {rejected || attempt.receipt?.status === "rejected"
          ? <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新讀取計畫</button>
          : <button disabled={busy} onClick={() => confirm(attempt)}>{attempt.receipt ? "重新確認變更" : "重試同一變更"}</button>}
      </>}
      <button disabled={busy || Boolean(attempt) || dirty || ambiguousPreferences || Boolean(restartTaskId && (restartSelection===undefined || (restartSelection && !canReuseDirection(visible,restartSelection))))} onClick={start}>使用已保存條件開始研究</button>
      <PlanHistory planId={visible.id} revision={visible.conditionsRevision} />
    </>}
  </section>;
}
