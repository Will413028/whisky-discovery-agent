"use client";

import {useEffect, useState} from "react";
import type {components} from "../../../../../contracts/api";
import validCatalog from "../../../../../contracts/catalog-view.validator.js";

type CatalogView = components["schemas"]["CatalogView"];
type Source = components["schemas"]["CatalogSourceView"];

function SourceLink({source}: {source:Source}) {
  return <><a href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher ?? source.url}</a>（查核日 {source.checkedOn}）</>;
}

export function Catalog() {
  const [catalog, setCatalog] = useState<CatalogView | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    setError(false);
    void (async () => {
      try {
        const response = await fetch("/api/v1/catalog", {cache:"no-store", signal:controller.signal});
        if (!response.ok) throw new Error("CATALOG_UNAVAILABLE");
        const value: unknown = await response.json();
        if (!validCatalog(value)) throw new Error("INVALID_RESPONSE");
        if (live) setCatalog(value);
      } catch {if (live) setError(true);}
    })();
    return () => {live = false; controller.abort();};
  }, [attempt]);
  if (error) return <p role="alert">暫時無法讀取已覆核酒款；請稍後重試。 <button onClick={() => setAttempt(value => value + 1)}>重新讀取酒款</button></p>;
  if (!catalog) return <p>載入已覆核酒款中…</p>;
  if (!catalog.items.length) return <p>目前沒有已覆核酒款。</p>;
  return <section aria-label="已覆核酒款">
    <p>價格資格判定日期：{catalog.evaluatedOn}。參考報價不代表即時庫存或可購買狀態。</p>
    {catalog.items.map(item => <article key={item.itemId}>
      <h2>{item.name}</h2><p>{item.versionLabel}</p>
      <p>酒精濃度：{item.abv ?? "未知"}{item.abv !== null && "%"}；容量：{item.volumeMl ?? "未知"}{item.volumeMl !== null && " ml"}</p>
      <p>編輯整理的風味標籤：{item.flavorTags.map(tag => tag.label).join("、") || "尚無整理標籤"}</p>
      <details><summary>已覆核描述與引用</summary>
        {item.claims.map(claim => <div key={`${claim.kind}:${claim.key}`}>
          <p>{claim.kind === "tag" && "編輯整理："}{claim.value}</p>
          {claim.sources.map(source => <p key={source.evidenceId}><SourceLink source={source} /></p>)}
        </div>)}
      </details>
      {item.priceQualification === "unqualified" && <p>未符合目前價格政策，不能用於嚴格預算判定。</p>}
      {item.priceUpperBoundTwd !== null && <p>符合政策的台灣單瓶參考價上緣：{item.priceUpperBoundTwd} TWD。</p>}
      {item.prices.map(price => <div key={price.id}>
        <p>參考報價：{price.amount ?? "未知"} {price.currency}／{price.volumeMl ?? "未知"} ml，{price.market}，查核日期 {price.checkedOn ?? "未知"}；{price.qualified ? "符合目前價格政策" : "不作嚴格預算依據"}。</p>
        <p><SourceLink source={price.source} /></p>
      </div>)}
    </article>)}
  </section>;
}
