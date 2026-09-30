"use client";

import {useAuth0} from "@auth0/auth0-react";
import {useEffect,useRef,useState} from "react";
import type {PlanView} from "./client";
import {readRestartContext,type RestartContext} from "./restart-client";

export function canReuseDirection(plan:PlanView,context:RestartContext):boolean {
  const saved=plan.conditions.starting_bottle;
  const source=context.sourceStartingBottle;
  return !saved || Boolean(source && saved.release_id===source.release_id && saved.item_id===source.item_id);
}

export function RestartDirection({plan,taskId,disabled,selected,onChange}:{plan:PlanView;taskId:string;disabled:boolean;selected:RestartContext|null|undefined;onChange:(context:RestartContext|null|undefined)=>void}) {
  const auth=useAuth0();
  const {getAccessTokenSilently}=auth;
  const subject=auth.user?.sub;
  const [context,setContext]=useState<RestartContext|null>(null);
  const [error,setError]=useState(false);
  const [refresh,setRefresh]=useState(0);
  const notify=useRef(onChange);
  notify.current=onChange;
  useEffect(()=>{
    let live=true;
    const controller=new AbortController();
    setContext(null);setError(false);notify.current(undefined);
    void(async()=>{
      try {
        const token=await getAccessTokenSilently();
        if(!live) return;
        if(!token) throw new Error("AUTH_REQUIRED");
        const next=await readRestartContext(plan.id,taskId,token,controller.signal);
        if(live) setContext(next);
      } catch {if(live){setError(true);notify.current(undefined);}}
    })();
    return()=>{live=false;controller.abort();};
  },[plan.id,taskId,subject,getAccessTokenSilently,refresh]);
  const compatible=context && canReuseDirection(plan,context);
  return <section aria-label="沿用研究方向">
    <h2>沿用已保存的研究方向</h2>
    {!context && !error && <p>讀取研究方向中…</p>}
    {error && <p role="alert">無法讀取可沿用的研究方向；未套用任何歷史資料。<button type="button" disabled={disabled} onClick={()=>setRefresh(value=>value+1)}>重新讀取研究方向</button></p>}
    {context && <>
      <p>沿用來源條件版本 {context.sourceConditionsRevision}；新研究使用目前已保存條件。</p>
      <p>方向：{{style_options:"有來源的風格選擇",similar:"接近熟悉口味",small_step:"小幅探索",contrast:"對照一項差異"}[context.input.intent.mode]}</p>
      {context.input.intent.origin_query && <p>上次起點：{context.input.intent.origin_query}；新研究會再次確認目前版本。</p>}
      {context.input.intent.explore_feature && <p>探索特徵：{context.input.intent.explore_feature}</p>}
      {context.input.intent.contrast && <p>描述對照：{context.input.intent.contrast.origin_feature} → {context.input.intent.contrast.candidate_feature}</p>}
      {context.input.intent.smoke_comparison && <p>煙燻比較仍需有一致證據，未知不會被當成較少。</p>}
      {!compatible && <p role="alert">計畫起點與這次研究不同，未沿用此方向；請先確認要使用的起點。</p>}
      <label><input type="checkbox" disabled={disabled || !compatible} checked={Boolean(selected)} onChange={event=>onChange(event.target.checked ? context : null)}/>沿用這次探索方向</label>
      <p>重新查核目前 catalog／價格；歷史報告保持原樣，不把旧參考價當目前報價。</p>
    </>}
    <button type="button" disabled={disabled} onClick={()=>onChange(null)}>不沿用此方向，使用已保存條件</button>
  </section>;
}
