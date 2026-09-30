import type {PreferenceProposalView} from "./proposal-client";

export function PreferenceProposalCard({view}:{view:PreferenceProposalView}) {
  return <section><h2>待確認偏好</h2>
    <p>原描述：</p><blockquote>{view.sourceText}</blockquote>
    <p>{view.proposal.summary}</p>
    {view.proposal.preferences.length === 0 && <p>尚無可確認的風味偏好；原描述仍可保留供後續探索。</p>}
    {view.proposal.preferences.map((suggestion,index)=><article key={index}>
      <h3>{suggestion.description}</h3>
      <p>{suggestion.source_kind === "food_clue" ? "飲食線索；偏好仍待確認" : "原描述線索；偏好仍待確認"}</p>
      <blockquote>{suggestion.source_quote}</blockquote>
      {suggestion.mapping && <p>對應覆核標籤：{suggestion.mapping.feature_key}</p>}
      <p>這個對應是推測；不會自動成為喜好或硬限制。</p>
    </article>)}
    {view.proposal.budget && <p>{view.proposal.budget.action === "clear" ? "原文建議：本次不設預算上限（待確認）" : `原文預算建議：新台幣 ${view.proposal.budget.amount_twd} 元（待確認）`}</p>}
    <p><a href={`/plans/${view.planId}?proposalTaskId=${view.taskId}`}>到計畫確認偏好與本次預算</a></p>
  </section>;
}
