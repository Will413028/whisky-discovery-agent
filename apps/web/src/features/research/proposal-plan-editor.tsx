"use client";

import {useAuth0} from "@auth0/auth0-react";
import {useEffect,useRef,useState} from "react";
import {readTask} from "./client";
import {readPreferenceProposal,type PreferenceProposalView} from "./proposal-client";
import {PreferenceProposalEditor,type ProposalPatch} from "./proposal-editor";

export async function readActivePlanProposal(taskId:string,planId:string,revision:number,token:string,signal?:AbortSignal) {
  const task=await readTask(taskId,token,signal);
  if(!task.question || Date.parse(task.question.expiresAt)<=Date.now()) return null;
  const view=await readPreferenceProposal(task,token,signal);
  return view && view.planId===planId && view.conditionsRevision===revision ? {view,expiresAt:task.question.expiresAt} : null;
}
export function proposalIdentity(view:PreferenceProposalView) {
  return JSON.stringify([view.taskId,view.questionId,view.waitingVersion,view.conditionsRevision]);
}
type Props={taskId:string;planId:string;revision:number;disabled:boolean;onChange:(patch:ProposalPatch | null)=>void;onBudgetChange:(value:string|null|undefined)=>void;budgetSelected:boolean;blockedFeatures:string[];onIdentity:(identity:string|null)=>void};
export function ProposalPlanEditor(props:Props) {
  const auth=useAuth0();
  return <ProposalPlanEditorSession key={JSON.stringify([auth.isAuthenticated,auth.user?.sub,props.taskId,props.planId,props.revision])} {...props}/>;
}
function ProposalPlanEditorSession({taskId,planId,revision,disabled,onChange,onBudgetChange,budgetSelected,blockedFeatures,onIdentity}:Props) {
  const auth=useAuth0();
  const [view,setView]=useState<PreferenceProposalView | null>(null);
  const [error,setError]=useState(false);
  const [closed,setClosed]=useState(false);
  const [refresh,setRefresh]=useState(0);
  const callbacks=useRef({onChange,onBudgetChange,onIdentity});
  callbacks.current={onChange,onBudgetChange,onIdentity};
  const {isAuthenticated,getAccessTokenSilently}=auth;
  useEffect(()=>{
    if(!isAuthenticated) return;
    let live=true,identity:string|null=null;
    let timer:ReturnType<typeof setTimeout>|undefined;
    let expiry:ReturnType<typeof setTimeout>|undefined;
    const controller=new AbortController();
    const invalidate=()=>{
      setView(null);setClosed(true);
      callbacks.current.onChange(null);callbacks.current.onBudgetChange(undefined);callbacks.current.onIdentity(null);
    };
    const load=async()=>{
      try {
        const token=await getAccessTokenSilently();
        if(!live) return;
        if(!token) throw new Error("AUTH_REQUIRED");
        const draft=await readActivePlanProposal(taskId,planId,revision,token,controller.signal);
        if(!live) return;
        if(!draft || (identity!==null && identity!==proposalIdentity(draft.view))) {invalidate();return;}
        identity=proposalIdentity(draft.view);
        callbacks.current.onIdentity(identity);
        setView(draft.view);setClosed(false);setError(false);
        clearTimeout(expiry);
        expiry=setTimeout(invalidate,Math.min(2147483647,Math.max(0,Date.parse(draft.expiresAt)-Date.now())));
        timer=setTimeout(()=>void load(),2500);
      } catch {if(live){invalidate();setError(true);}}
    };
    void load();
    return ()=>{live=false;controller.abort();clearTimeout(timer);clearTimeout(expiry);};
  },[isAuthenticated,getAccessTokenSilently,taskId,planId,revision,refresh]);
  if(!isAuthenticated) return null;
  if(error) return <p role="alert">偏好草稿暫時無法讀取。<button type="button" onClick={()=>setRefresh(value=>value+1)}>重新讀取草稿</button></p>;
  if(closed) return <p>此草稿已關閉或條件版本已變更，請使用目前已保存的條件。</p>;
  if(!view) return <p>讀取偏好草稿中…</p>;
  return <PreferenceProposalEditor key={proposalIdentity(view)} view={view} disabled={disabled} onChange={onChange} onBudgetChange={onBudgetChange} budgetSelected={budgetSelected} blockedFeatures={blockedFeatures}/>;
}
