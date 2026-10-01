import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,expect,test} from "vitest";
import {PreferenceProposalCard} from "./proposal-ui";
import type {PreferenceProposalView} from "./proposal-client";

afterEach(cleanup);
const id="00000000-0000-4000-8000-000000000001";
const view:PreferenceProposalView={schemaVersion:4,taskId:id,planId:id,questionId:id,conditionsRevision:1,waitingVersion:1,sourceText:"我喜歡水果甜點",proposal:{summary:"飲食只是線索",intent:{mode:"style_options",origin_query:null,explore_feature:null,contrast:null,smoke_comparison:false},budget:null,preferences:[{description:"可能喜歡果香",intent:"prefer",source_quote:"喜歡水果甜點",source_kind:"food_clue",certainty:"inferred",strength:"soft",mapping:{feature_key:"果香",reference:{release_id:id,item_id:id},evidence_ids:[id]}}]}};

test("the preference card distinguishes the original food clue from an unconfirmed reviewed-tag mapping",()=>{
  render(<PreferenceProposalCard view={view}/>);
  expect(screen.getByText("我喜歡水果甜點")).toBeTruthy();
  expect(screen.getByText("可能喜歡果香")).toBeTruthy();
  expect(screen.getByText("喜歡水果甜點")).toBeTruthy();
  expect(screen.getByText("對應覆核標籤：果香")).toBeTruthy();
  expect(screen.getByText("飲食線索；偏好仍待確認")).toBeTruthy();
});

test("a mapping-free proposal honestly preserves the absence of a reliable taste mapping",()=>{
  render(<PreferenceProposalCard view={{...view,proposal:{...view.proposal,summary:"目前無可靠映射",preferences:[]}}}/>);
  expect(screen.getByText("目前無可靠映射")).toBeTruthy();
  expect(screen.getByText("尚無可確認的風味偏好；原描述仍可保留供後續探索。")).toBeTruthy();
});
