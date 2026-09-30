import type {ComparisonReportView} from "./comparison-client";

type Item = ComparisonReportView["items"][number];

function Sources({item}:{item:Item | undefined}) {
  return <>{item?.sources.map(source=><p key={source.evidenceId}>來源：<a href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher ?? source.url}</a>（查核日期 {source.checkedOn}）</p>)}</>;
}

export function ComparisonReport({view}:{view:ComparisonReportView}) {
  const itemFor=(reference:ComparisonReportView["items"][number]["reference"] | null)=>reference && view.items.find(item=>item.reference.item_id===reference.item_id && item.reference.release_id===reference.release_id) || undefined;
  return <section aria-label="已覆核風味比較">
    <h3>已覆核風味比較</h3>
    <p>依 {view.evaluatedOn} 的已覆核資料整理；條件版本 {view.conditionsRevision}。</p>
    {view.comparison.unlistedName && <p>未收錄起點：{view.comparison.unlistedName}</p>}
    {view.comparison.unresolved.map(value=><p key={value}>{value}</p>)}
    {view.comparison.candidates.map(candidate=>{
      const target=itemFor(candidate.candidate);
      const origin=itemFor(candidate.origin);
      const name=target?.name ?? "候選酒款";
      const common=[...new Set(candidate.candidateClaims.filter(claim=>candidate.commonTags.includes(claim.key)).map(claim=>claim.value))];
      return <section key={`${candidate.candidate.release_id}:${candidate.candidate.item_id}`} aria-label={`${name}的比較`}>
        <h4>{name}</h4>
        {Boolean(common.length) && <p>共同風味：{common.join("、")}</p>}
        {origin && <div><p>起點：{origin.name}</p>{candidate.originDescription && <p>{candidate.originDescription.value}</p>}<Sources item={origin}/></div>}
        <div><p>候選：{name}</p>{candidate.candidateDescription && <p>{candidate.candidateDescription.value}</p>}<Sources item={target}/></div>
        {candidate.difference && <p>已覆核描述差異：起點為「{candidate.difference.originFeature}」，候選為「{candidate.difference.candidateFeature}」。</p>}
        {Boolean(candidate.exploreClaims.length) && <p>可探索風味：{[...new Set(candidate.exploreClaims.map(claim=>claim.value))].join("、")}</p>}
      </section>;
    })}
  </section>;
}
