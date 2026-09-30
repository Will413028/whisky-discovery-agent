"use client";

import {useAuth0} from "@auth0/auth0-react";
import {useEffect,useRef,useState} from "react";
import {listHistory,type HistoryItem} from "./history-client";

export function PlanHistory({planId, revision}: {planId:string; revision:number}) {
  const auth=useAuth0();
  const {isAuthenticated,getAccessTokenSilently}=auth;
  const subject=auth.user?.sub;
  const [items,setItems]=useState<HistoryItem[] | null>(null);
  const [cursor,setCursor]=useState<string | null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(false);
  const life=useRef(0);
  const load=(next:string | null,generation:number,reset:boolean,signal?:AbortSignal)=>{
    setBusy(true);setError(false);
    void (async()=>{
      try {
        const token=await getAccessTokenSilently();
        if (generation!==life.current) return;
        if (!token) throw new Error("AUTH_REQUIRED");
        const page=await listHistory(planId,token,next,signal);
        if (generation!==life.current) return;
        setItems(previous=>[...new Map([...(reset ? [] : previous ?? []),...page.items].map(item=>[item.task.taskId,item])).values()]);
        setCursor(page.nextCursor);
      } catch {if(generation===life.current)setError(true);}
      finally {if(generation===life.current)setBusy(false);}
    })();
  };
  useEffect(()=>{
    const generation=++life.current;
    setItems(null);setCursor(null);setError(false);setBusy(false);
    if (!isAuthenticated) return;
    const controller=new AbortController();
    load(null,generation,true,controller.signal);
    return ()=>{life.current++;controller.abort();};
  },[planId,revision,isAuthenticated,getAccessTokenSilently,subject]);
  if (!isAuthenticated || auth.isLoading) return null;
  return <section aria-label="研究紀錄">
    <h2>研究紀錄</h2>
    <a href={`/plans/${planId}/conclusions`}>查看保存的探索結論</a>
    {error && <p role="alert">暫時無法讀取研究紀錄。<button disabled={busy} onClick={()=>load(cursor,life.current,items===null)}>重新讀取研究紀錄</button></p>}
    {!items && !error && <p>讀取研究紀錄中…</p>}
    {items?.length===0 && <p>尚未有研究紀錄。</p>}
    {items && items.length>0 && <ul>{items.map(item=><li key={item.task.taskId}>
      <p>{item.task.conditionsRevision===revision ? "目前" : "歷史"}條件版本 {item.task.conditionsRevision}</p>
      <time dateTime={item.createdAt}>{item.createdAt}</time>{" "}
      <a href={`/research/${item.task.taskId}`}>查看研究 {item.task.status}</a>
      {item.task.status==="completed" && <a href={`/plans/${planId}?restartTaskId=${item.task.taskId}`}>查看可沿用的探索方向</a>}
    </li>)}</ul>}
    {cursor && !error && <button disabled={busy} onClick={()=>load(cursor,life.current,false)}>讀取更多研究</button>}
  </section>;
}
