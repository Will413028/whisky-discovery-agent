import {expect,test} from "vitest";
import {preferencePatch,savedPreferences,selectProposal,type Preference} from "./preference-draft";
const fruit:Preference={description:"果香",intent:"keep",certainty:"user_stated",strength:"soft"};
const honey:Preference={description:"蜂蜜",intent:"change",certainty:"user_stated",strength:"soft"};
test("proposal invalidation restores saved preferences but preserves explicitly manual edits",()=>{
  const original=[fruit];
  const selected=selectProposal(savedPreferences(original),original,[{...fruit,intent:"prefer"},honey]);
  expect(selected.map(row=>row.value)).toEqual([{...fruit,intent:"prefer"},honey]);
  const manual=selected.map(row=>row.value.description==="蜂蜜" ? {...row,source:"manual" as const,value:{...honey,strength:"hard" as const}} : row);
  const invalidated=selectProposal(manual,original,[]);
  expect(invalidated.map(row=>row.value)).toEqual([fruit,{...honey,strength:"hard"}]);
  expect(preferencePatch(original,invalidated)).toEqual({upsert_preferences:[{...honey,strength:"hard"}],remove_preferences:[]});
});
test("only explicitly changed or removed preferences enter the command patch",()=>{
  expect(preferencePatch([fruit,honey],[{value:{...fruit,intent:"avoid"},source:"manual"}])).toEqual({upsert_preferences:[{...fruit,intent:"avoid"}],remove_preferences:["蜂蜜"]});
  expect(preferencePatch([fruit],savedPreferences([fruit]))).toEqual({upsert_preferences:[],remove_preferences:[]});
});

test("removing one legacy same-description preference emits explicit replacement of the remaining value",()=>{
  const other={...fruit,intent:"prefer" as const};
  expect(preferencePatch([fruit,other],[{value:fruit,source:"saved"},{value:other,source:"manual",removed:true}])).toEqual({upsert_preferences:[fruit],remove_preferences:["果香"]});
});
test("manual removal cannot be resurrected by a proposal refresh or invalidation",()=>{
  const removed=[{value:fruit,source:"manual" as const,removed:true as const}];
  expect(selectProposal(removed,[fruit],[fruit])).toEqual(removed);
  expect(preferencePatch([fruit],selectProposal(removed,[fruit],[]))).toEqual({upsert_preferences:[],remove_preferences:["果香"]});
});

test("proposal invalidation preserves an untouched same-description legacy preference beside a manual removal",()=>{
  const other={...fruit,intent:"prefer" as const};
  const current=[{value:fruit,source:"saved" as const},{value:other,source:"manual" as const,removed:true as const}];
  const restored=selectProposal(current,[fruit,other],[]);
  expect(restored).toEqual(current);
  expect(selectProposal(current,[fruit,other],[{...fruit,intent:"avoid"}])).toEqual(current);
  expect(preferencePatch([fruit,other],restored)).toEqual({upsert_preferences:[fruit],remove_preferences:["果香"]});
});

test("editing an ambiguous legacy group cannot silently remove its untouched sibling",()=>{
  const other={...fruit,intent:"prefer" as const};
  expect(preferencePatch([fruit,other],[{value:{...fruit,strength:"hard"},source:"manual"},{value:other,source:"saved"}])).toEqual({upsert_preferences:[],remove_preferences:[]});
});

test("selecting a proposal cannot replace an unresolved legacy same-description group",()=>{
  const other={...fruit,intent:"avoid" as const};
  const current=savedPreferences([fruit,other]);
  expect(selectProposal(current,[fruit,other],[{...fruit,intent:"prefer"}])).toEqual(current);
});
