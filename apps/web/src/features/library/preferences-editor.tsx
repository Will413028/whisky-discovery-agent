"use client";
import {useEffect,useRef,useState} from "react";
import {PreferencesRejected,readLongTermPreferences,saveLongTermPreferences,type LongTermPreference,type SaveLongTermPreferences} from "./preferences-client";
export type FeedbackPreferenceSource={id:string;revision:number;reason:string};
export function LongTermPreferencesEditor({token,source}:{token:()=>Promise<string>;source?:FeedbackPreferenceSource}){
  const [values,setValues]=useState<LongTermPreference[]>([]);
  const [revision,setRevision]=useState(0);
  const [description,setDescription]=useState("");
  const [statement,setStatement]=useState("");
  const [intent,setIntent]=useState<"prefer"|"avoid">("prefer");
  const [hard,setHard]=useState(false);
  const [status,setStatus]=useState<"loading"|"ready"|"saving"|"unknown"|"rejected"|"read_failed">("loading");
  const [message,setMessage]=useState("");
  const [refresh,setRefresh]=useState(0);
  const attempt=useRef<SaveLongTermPreferences|null>(null);
  const epoch=useRef(0);
  useEffect(()=>{
    const current=++epoch.current;const controller=new AbortController();
    setStatus("loading");setMessage("");attempt.current=null;
    void token().then(access=>{if(current!==epoch.current)throw new Error("SESSION_CHANGED");return readLongTermPreferences(access,controller.signal);}).then(value=>{
      if(current!==epoch.current)return;
      setValues(value.preferences);setRevision(value.revision);setStatus("ready");
      setDescription("");setStatement("");setIntent("prefer");setHard(false);
    }).catch(()=>{if(current===epoch.current)setStatus("read_failed");});
    return ()=>{++epoch.current;controller.abort();};
  },[token,refresh]);
  function add(){
    if(!description.trim() || !statement.trim()){setMessage("請填寫偏好特徵及自己的明確陳述。");return;}
    if(values.length>=64 || values.some(value=>value.description===description.trim())){setMessage("這個特徵已存在，或已達偏好數量上限；可先移除原項目再修改。");return;}
    setValues(previous=>[...previous,{description:description.trim(),intent,strength:hard ? "hard" : "soft",certainty:"user_stated",statement:statement.trim(),sourceFeedbackId:source?.id ?? null,sourceFeedbackRevision:source?.revision ?? null}]);
    setDescription("");setStatement("");setMessage("偏好尚未保存，請確認後保存。");
  }
  async function save(){
    const current=epoch.current;
    const command=attempt.current ?? {schemaVersion:1 as const,key:crypto.randomUUID(),expectedRevision:revision,preferences:values.map(value=>({...value}))};
    attempt.current=command;setStatus("saving");setMessage("");
    try {
      const access=await token();if(current!==epoch.current)return;
      const value=await saveLongTermPreferences(command,access);if(current!==epoch.current)return;
      setValues(value.preferences);setRevision(value.revision);attempt.current=null;setStatus("ready");setMessage("長期偏好已保存。");
    } catch(error){
      if(current!==epoch.current)return;
      if(error instanceof PreferencesRejected){attempt.current=null;setStatus("rejected");setMessage("保存未接受，請重新讀取長期偏好；回饋來源若已修改，請重新選取。");}
      else {setStatus("unknown");setMessage("尚未確認保存結果，可重送同一偏好。");}
    }
  }
  if(status==="loading")return <p>正在讀取長期偏好。</p>;
  if(status==="read_failed")return <p role="alert">暫時無法讀取長期偏好。<button onClick={()=>setRefresh(value=>value+1)}>重新讀取長期偏好</button></p>;
  return <section aria-label="長期明確偏好"><h2>長期明確偏好</h2>
    <p>只保存你明確說出的喜歡或排斥。收藏、喜歡一支酒與本次預算不會自動成為長期偏好；新探索時可自行選擇套用。</p>
    {source && <p>來源回饋：{source.reason || "未填原因"}；新增特徵仍需你親自明述。</p>}
    <fieldset disabled={status!=="ready"}><legend>我的明確偏好</legend>
      {values.map(value=><div key={value.description}><p>{value.description}：{value.intent==="prefer" ? "喜歡" : "排斥"}（{value.strength==="hard" ? "硬限制" : "軟偏好"}）</p><p>{value.statement}</p><button onClick={()=>setValues(previous=>previous.filter(item=>item.description!==value.description))}>移除偏好 {value.description}</button></div>)}
      <label>偏好特徵<input maxLength={1000} value={description} onChange={event=>setDescription(event.target.value)}/></label>
      <label>偏好方向<select value={intent} onChange={event=>setIntent(event.target.value as typeof intent)}><option value="prefer">喜歡</option><option value="avoid">排斥</option></select></label>
      <label>我的明確陳述<textarea maxLength={2000} value={statement} onChange={event=>setStatement(event.target.value)}/></label>
      <label><input type="checkbox" checked={hard} onChange={event=>setHard(event.target.checked)}/>套用時作為硬限制</label>
      <button onClick={add}>加入明確偏好</button><button onClick={()=>void save()}>保存長期偏好</button>
    </fieldset>
    {message && <p role="status">{message}</p>}
    {status==="unknown" && <button onClick={()=>void save()}>重送同一偏好</button>}
    {status==="rejected" && <button onClick={()=>setRefresh(value=>value+1)}>重新讀取長期偏好</button>}
  </section>;
}
