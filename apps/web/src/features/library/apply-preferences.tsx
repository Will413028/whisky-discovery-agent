"use client";
import type {LongTermPreference} from "./preferences-client";
import {readLongTermPreferences} from "./preferences-client";
import {useEffect,useState} from "react";
export function ApplyLongTermPreferences({token,onChange,disabled=false}:{token:()=>Promise<string>;onChange:(values:LongTermPreference[])=>void;disabled?:boolean}){
  const [values,setValues]=useState<LongTermPreference[]|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [failed,setFailed]=useState(false);
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let live=true;const controller=new AbortController();setValues(null);setFailed(false);
    void token().then(access=>{if(!live)throw new Error("SESSION_CHANGED");return readLongTermPreferences(access,controller.signal);}).then(value=>{
      if(live){setValues(value.preferences);setSelected([]);}
    }).catch(()=>{if(live)setFailed(true);});
    return ()=>{live=false;controller.abort();};
  },[token,refresh]);
  if(failed)return <p role="alert">暫時無法讀取已存偏好；仍可不套用並開始新探索。<button type="button" disabled={disabled} onClick={()=>{onChange([]);setRefresh(value=>value+1);}}>重新讀取已存偏好</button></p>;
  if(!values)return <p>正在讀取已存偏好。</p>;
  if(values.length===0)return <p>尚未保存長期偏好。<a href="/library">管理自己的偏好</a></p>;
  return <fieldset disabled={disabled}><legend>自行選擇套用已存偏好</legend><p>只有勾選的特徵會套用；預算由這次探索另行設定。</p>
    {values.map(value=><label key={value.description}><input type="checkbox" aria-label={`套用 ${value.description}`} checked={selected.includes(value.description)} onChange={event=>{
      const next=event.target.checked ? [...selected,value.description] : selected.filter(description=>description!==value.description);
      setSelected(next);onChange(values.filter(item=>next.includes(item.description)));
    }}/>{`套用 ${value.description}`}（{value.intent==="prefer" ? "喜歡" : "排斥"}、{value.strength==="hard" ? "硬限制" : "軟偏好"}）：{value.statement}</label>)}
  </fieldset>;
}
