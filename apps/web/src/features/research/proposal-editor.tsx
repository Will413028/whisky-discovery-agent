import type {components} from "../../../../../contracts/api";
import type {PreferenceProposalView} from "./proposal-client";
import {PreferenceProposalCard} from "./proposal-ui";

export type ProposalPatch = components["schemas"]["PatchConditionsRequest"]["patch"];
export function PreferenceProposalEditor({view,onChange,onBudgetChange,budgetSelected=false,blockedFeatures=[],disabled=false}:{view:PreferenceProposalView;onChange:(patch:ProposalPatch | null)=>void;onBudgetChange?:(value:string|null|undefined)=>void;budgetSelected?:boolean;blockedFeatures?:string[];disabled?:boolean}) {
  const [selected,setSelected]=useState<number[]>([]);
  const [hard,setHard]=useState<number[]>([]);
  const emit=(next:number[],limits:number[])=>{
    setSelected(next);setHard(limits);
    if(next.length===0){onChange(null);return;}
    const patch:ProposalPatch={upsert_preferences:next.map(index=>{
      const suggestion=view.proposal.preferences[index];
      return {description:suggestion.mapping?.feature_key ?? suggestion.description,intent:suggestion.intent,certainty:"user_stated",strength:limits.includes(index) ? "hard" : "soft"};
    }),remove_preferences:[]};
    onChange(patch);
  };
  return <><PreferenceProposalCard view={view}/><fieldset disabled={disabled}><legend>確認偏好草稿</legend>
    <p>只保存你勾選的項目；硬限制與預算需要另行勾選。</p>
    {view.proposal.preferences.map((suggestion,index)=><div key={index}>
      <label><input type="checkbox" disabled={blockedFeatures.includes(suggestion.mapping?.feature_key ?? suggestion.description)} checked={selected.includes(index)} onChange={event=>emit(event.target.checked ? [...selected,index] : selected.filter(value=>value!==index),hard.filter(value=>value!==index))}/>確認偏好：{suggestion.description}</label>
      <label><input type="checkbox" disabled={!selected.includes(index) || blockedFeatures.includes(suggestion.mapping?.feature_key ?? suggestion.description)} checked={hard.includes(index)} onChange={event=>emit(selected,event.target.checked ? [...hard,index] : hard.filter(value=>value!==index))}/>設為硬限制：{suggestion.description}</label>
    </div>)}
    {view.proposal.budget && <label><input type="checkbox" checked={budgetSelected} onChange={event=>onBudgetChange?.(event.target.checked ? view.proposal.budget!.amount_twd : undefined)}/>{view.proposal.budget.action === "clear" ? "確認本次不設預算上限" : `確認本次預算：新台幣${view.proposal.budget.amount_twd}元`}</label>}
  </fieldset></>;
}
import {useState} from "react";
