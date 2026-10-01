"use client";
import {useEffect,useRef,useState} from "react";
import {FeedbackRejected,readBottleFeedback,saveBottleFeedback,type BottleFeedback,type SaveBottleFeedback} from "./feedback-client";
export function BottleFeedbackEditor({version,name,token}:{version:string;name:string;token:()=>Promise<string>}) {
  const [want,setWant]=useState(false);
  const [tasting,setTasting]=useState<BottleFeedback["tasting"]>("not_tasted");
  const [reason,setReason]=useState("");
  const [revision,setRevision]=useState(0);
  const [state,setState]=useState<"loading"|"ready"|"saving"|"unknown"|"rejected"|"read_failed">("loading");
  const [message,setMessage]=useState("");
  const [refresh,setRefresh]=useState(0);
  const attempt=useRef<SaveBottleFeedback|null>(null);
  const epoch=useRef(0);
  useEffect(()=>{
    const current=++epoch.current;
    const controller=new AbortController();
    setState("loading");setMessage("");attempt.current=null;
    void token().then(value=>readBottleFeedback(version,value,controller.signal)).then(value=>{
      if(current!==epoch.current)return;
      setWant(value?.wantToExplore ?? false);setTasting(value?.tasting ?? "not_tasted");
      setReason(value?.tastingReason ?? "");setRevision(value?.revision ?? 0);setState("ready");
    }).catch(()=>{if(current===epoch.current)setState("read_failed");});
    return ()=>{++epoch.current;controller.abort();};
  },[version,token,refresh]);
  async function save() {
    const current=epoch.current;
    const command=attempt.current ?? {schemaVersion:1 as const,key:crypto.randomUUID(),bottleVersionId:version,expectedRevision:revision,wantToExplore:want,tasting,tastingReason:tasting==="not_tasted" ? "" : reason};
    attempt.current=command;setState("saving");setMessage("");
    try {
      const access=await token();if(current!==epoch.current)return;
      const result=await saveBottleFeedback(command,access);
      if(current!==epoch.current)return;
      setRevision(result.revision);setWant(result.wantToExplore);setTasting(result.tasting);setReason(result.tastingReason);
      attempt.current=null;setState("ready");setMessage("酒款回饋已保存。");
    } catch(error) {
      if(current!==epoch.current)return;
      if(error instanceof FeedbackRejected){attempt.current=null;setState("rejected");setMessage("保存未接受，請重新讀取回饋後再修改。");}
      else {setState("unknown");setMessage("尚未確認保存結果，可重送同一回饋。");}
    }
  }
  if(state==="loading")return <p>正在讀取酒款回饋。</p>;
  if(state==="read_failed")return <div><p>無法讀取酒款回饋。</p><button onClick={()=>setRefresh(value=>value+1)}>重新讀取回饋</button></div>;
  return <section aria-label={`${name}的酒款回饋`}>
    <fieldset disabled={state!=="ready"}>
      <legend>酒款回饋</legend>
      <label><input type="checkbox" checked={want} onChange={event=>setWant(event.target.checked)}/>想探索（收藏）</label>
      <label>品飲感受<select value={tasting} onChange={event=>{const value=event.target.value as BottleFeedback["tasting"];setTasting(value);if(value==="not_tasted")setReason("");}}>
        <option value="not_tasted">尚未品飲</option><option value="liked">喜歡</option><option value="disliked">不喜歡</option>
      </select></label>
      <label>品飲原因<textarea value={reason} maxLength={2000} disabled={tasting==="not_tasted"} onChange={event=>setReason(event.target.value)}/></label>
      <button onClick={()=>void save()}>保存酒款回饋</button>
    </fieldset>
    {message && <p role="status">{message}</p>}
    {state==="unknown" && <button onClick={()=>void save()}>重送同一回饋</button>}
    {state==="rejected" && <button onClick={()=>setRefresh(value=>value+1)}>重新讀取回饋</button>}
  </section>;
}
