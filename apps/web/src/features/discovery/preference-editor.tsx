import {useState} from "react";
import {duplicatePreferenceDescriptions,type Preference,type PreferenceDraft} from "./preference-draft";

export function PreferenceEditor({draft,onChange,disabled}:{draft:PreferenceDraft[];onChange:(draft:PreferenceDraft[])=>void;disabled:boolean}) {
  const duplicates=duplicatePreferenceDescriptions(draft);
  const [description,setDescription]=useState("");
  const [intent,setIntent]=useState<Preference["intent"]>("prefer");
  const [error,setError]=useState<string|null>(null);
  const edit=(index:number,value:Preference)=>onChange(draft.map((row,i)=>i===index ? {value,source:"manual"} : row));
  const add=()=>{
    const label=description.trim();
    if(!label) return;
    if(draft.some(row=>!row.removed && row.value.description===label)) {setError("這個特徵已存在，請修改原項目。");return;}
    if(draft.filter(row=>!row.removed).length>=64) {setError("偏好項目已達上限，請先移除項目。");return;}
    onChange([...draft.filter(row=>row.value.description!==label),{value:{description:label,intent,certainty:"user_stated",strength:"soft"},source:"manual"}]);
    setDescription("");setError(null);
  };
  return <fieldset disabled={disabled}><legend>本次偏好與限制</legend>
    {draft.filter(row=>!row.removed).length===0 && <p>尚未指定偏好；未知項目可以保持空白。</p>}
    {duplicates.map(description=><p key={description} role="alert">{description}有多個同名偏好，請先移除到只剩一項再修改。</p>)}
    {draft.map((row,index)=>row.removed ? null : <div key={index}>
      <p>{row.value.description} — {row.value.certainty==="inferred" ? "待確認推測" : row.value.certainty==="unknown" ? "尚未確認" : "已明確指定"}</p>
      <label>{row.value.description}的偏好用途<select disabled={duplicates.includes(row.value.description)} value={row.value.intent} onChange={event=>edit(index,{...row.value,intent:event.target.value as Preference["intent"],certainty:"user_stated"})}><option value="prefer">喜歡</option><option value="keep">本次保留</option><option value="change">本次探索</option><option value="avoid">排斥</option></select></label>
      <label><input type="checkbox" disabled={duplicates.includes(row.value.description)} checked={row.value.strength==="hard"} onChange={event=>edit(index,{...row.value,strength:event.target.checked ? "hard" : "soft",certainty:"user_stated"})}/>{row.value.description}設為硬限制</label>
      <button type="button" onClick={()=>onChange(draft.map((item,i)=>i===index ? {...item,source:"manual",removed:true} : item))}>移除偏好：{row.value.description}</button>
    </div>)}
    <label>新增風味特徵<input maxLength={1000} value={description} onChange={event=>setDescription(event.target.value)}/></label>
    <label>新特徵用途<select value={intent} onChange={event=>setIntent(event.target.value as Preference["intent"])}><option value="prefer">喜歡</option><option value="keep">本次保留</option><option value="change">本次探索</option><option value="avoid">排斥</option></select></label>
    <button type="button" onClick={add}>加入本次偏好</button>
    {error && <p role="alert">{error}</p>}
  </fieldset>;
}
