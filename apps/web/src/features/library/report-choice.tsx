"use client";
import {useEffect,useState} from "react";
import {ConclusionChoice} from "./choice";
import {readConclusionContext} from "./client";

export function ReportConclusion({reportId,taskId,revision,candidates,getToken}:{reportId:string;taskId:string;revision:number;candidates:{versionId:string;name:string}[];getToken:()=>Promise<string>}) {
  const [context,setContext]=useState<Awaited<ReturnType<typeof readConclusionContext>>|null>(null);
  const [error,setError]=useState(false);
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let live=true;const controller=new AbortController();setContext(null);setError(false);
    void (async()=>{
      try {const token=await getToken();if(!live)return;
        const value=await readConclusionContext(reportId,taskId,revision,token,controller.signal);if(live)setContext(value);
      } catch {if(live)setError(true);}
    })();
    return ()=>{live=false;controller.abort();};
  },[reportId,taskId,revision,getToken,refresh]);
  if(error) return <p>暫時無法確認結論保存資格。<button onClick={()=>setRefresh(value=>value+1)}>重新確認保存資格</button></p>;
  if(!context || context.reportId!==reportId || context.taskId!==taskId || context.conditionsRevision!==revision) return <p>確認結論保存資格中…</p>;
  if(context.currentConditionsRevision!==revision) return <p>這份報告屬於歷史條件，請先依目前條件完成新研究，再保存結論。</p>;
  return <ConclusionChoice key={`${context.planId}:${reportId}:${revision}`} planId={context.planId} reportId={reportId} revision={revision} candidates={candidates} getToken={getToken}/>;
}
