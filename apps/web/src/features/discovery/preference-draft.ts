import type {components} from "../../../../../contracts/api";

export type Preference=components["schemas"]["Preference"];
export type PreferenceDraft={value:Preference;source:"saved"|"manual"|"proposal";removed?:true};
export function savedPreferences(values:Preference[]):PreferenceDraft[] {return values.map(value=>({value,source:"saved"}));}
export function selectProposal(current:PreferenceDraft[],saved:Preference[],selected:Preference[]):PreferenceDraft[] {
  const manual=current.filter(row=>row.source==="manual");
  const manualKeys=new Set(manual.map(row=>row.value.description));
  const blocked=new Set(duplicatePreferenceDescriptions(current));
  selected=selected.filter(value=>!blocked.has(value.description));
  const selectedKeys=new Set(selected.map(value=>value.description));
  const retained=current.filter(row=>row.source!=="proposal");
  const retainedKeys=new Set(retained.map(row=>row.value.description));
  const result=[
    ...retained.filter(row=>row.source==="manual" || manualKeys.has(row.value.description) || !selectedKeys.has(row.value.description)),
    ...savedPreferences(saved.filter(value=>!retainedKeys.has(value.description) && !selectedKeys.has(value.description))),
    ...selected.filter(value=>!manualKeys.has(value.description)).map(value=>({value,source:"proposal" as const})),
  ];
  const order=new Map(saved.map((value,index)=>[value.description,index]));
  return result.sort((left,right)=>(order.get(left.value.description) ?? saved.length)-(order.get(right.value.description) ?? saved.length));
}
export function duplicatePreferenceDescriptions(draft:PreferenceDraft[]):string[] {
  const counts=new Map<string,number>();
  for(const row of draft) if(!row.removed) counts.set(row.value.description,(counts.get(row.value.description) ?? 0)+1);
  return [...counts].filter(([,count])=>count>1).map(([description])=>description);
}
export function hasAmbiguousPreferenceEdits(draft:PreferenceDraft[]):boolean {
  return duplicatePreferenceDescriptions(draft).some(description=>draft.some(row=>row.value.description===description && row.source!=="saved"));
}
export function preferencePatch(saved:Preference[],draft:PreferenceDraft[]) {
  if(hasAmbiguousPreferenceEdits(draft)) return {upsert_preferences:[],remove_preferences:[]};
  const visible=draft.filter(row=>!row.removed).map(row=>row.value);
  const keys=new Set(visible.map(value=>value.description));
  const changed=visible.filter(value=>!saved.some(previous=>samePreference(previous,value)));
  const removed=new Set(saved.filter(value=>!keys.has(value.description)).map(value=>value.description));
  for(const description of keys) {
    const previous=saved.filter(value=>value.description===description);
    const remaining=visible.filter(value=>value.description===description);
    if(previous.length>1 && previous.length!==remaining.length) {
      removed.add(description);
      for(const value of remaining) if(!changed.includes(value)) changed.push(value);
    }
  }
  for(const value of changed) {
    if(saved.filter(previous=>previous.description===value.description).length>1) removed.add(value.description);
  }
  return {upsert_preferences:changed,remove_preferences:[...removed]};
}

function samePreference(left:Preference,right:Preference) {
  return left.description===right.description && left.intent===right.intent && left.certainty===right.certainty && left.strength===right.strength;
}
