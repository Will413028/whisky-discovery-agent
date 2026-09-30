import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {PreferenceProposalEditor} from "./proposal-editor";
import type {PreferenceProposalView} from "./proposal-client";

afterEach(cleanup);
const id="00000000-0000-4000-8000-000000000001";
const view:PreferenceProposalView={schemaVersion:4,taskId:id,planId:id,questionId:id,conditionsRevision:1,waitingVersion:1,sourceText:"我喜歡水果甜點，預算1000元",proposal:{summary:"待確認",intent:{mode:"style_options",origin_query:null,explore_feature:null,contrast:null,smoke_comparison:false},budget:{action:"set",amount_twd:"1000.00",source_quote:"預算1000元"},preferences:[{description:"可能喜歡果香",intent:"prefer",source_quote:"喜歡水果甜點",source_kind:"food_clue",certainty:"inferred",strength:"soft",mapping:{feature_key:"果香",reference:{release_id:id,item_id:id},evidence_ids:[id]}}]}};

test("explicit selection emits the reviewed key as soft user-stated without applying the model's budget",()=>{
  const change=vi.fn();render(<PreferenceProposalEditor view={view} onChange={change}/>);
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("確認偏好：可能喜歡果香"));
  expect(change).toHaveBeenLastCalledWith({upsert_preferences:[{description:"果香",intent:"prefer",certainty:"user_stated",strength:"soft"}],remove_preferences:[]});
  expect(view.proposal.preferences[0].certainty).toBe("inferred");
  fireEvent.click(screen.getByLabelText("設為硬限制：可能喜歡果香"));
  expect(change.mock.lastCall?.[0].upsert_preferences[0].strength).toBe("hard");
});

test("budget selection emits a separate value without duplicating it in the preference patch",()=>{
  const change=vi.fn(),budget=vi.fn();
  const {rerender}=render(<PreferenceProposalEditor view={view} onChange={change} onBudgetChange={budget}/>);
  fireEvent.click(screen.getByLabelText("確認本次預算：新台幣1000.00元"));
  expect(budget).toHaveBeenLastCalledWith("1000.00");
  expect(change).not.toHaveBeenCalled();
  rerender(<PreferenceProposalEditor view={view} onChange={change} onBudgetChange={budget} budgetSelected/>);
  fireEvent.click(screen.getByLabelText("確認本次預算：新台幣1000.00元"));
  expect(budget).toHaveBeenLastCalledWith(undefined);
});

test("a budget-clear draft requires an explicit opt-in and emits null without inventing an amount",()=>{
  const change=vi.fn(),budget=vi.fn();
  render(<PreferenceProposalEditor view={{...view,sourceText:"我喜歡水果甜點，不設預算",proposal:{...view.proposal,budget:{action:"clear",amount_twd:null,source_quote:"不設預算"}}}} onChange={change} onBudgetChange={budget}/>);
  expect(budget).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("確認本次不設預算上限"));
  expect(budget).toHaveBeenLastCalledWith(null);
  expect(change).not.toHaveBeenCalled();
});
