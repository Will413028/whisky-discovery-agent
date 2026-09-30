"use client";
import type {Conclusion} from "./client";
import {revisitConclusion,type ConclusionRevisit} from "./client";
import {useEffect,useState} from "react";
export function CurrentQualification({saved,token}:{saved:Conclusion;token:()=>Promise<string>}) {
  const [current,setCurrent]=useState<ConclusionRevisit|null>(null);
  const [failed,setFailed]=useState(false);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let live=true;const controller=new AbortController();
    setCurrent(null);setFailed(false);
    void (async()=>{
      try {
        const access=await token();if(!live)return;
        if(!access)throw new Error("AUTH_REQUIRED");
        const value=await revisitConclusion(saved,access,controller.signal);
        if(live)setCurrent(value);
      } catch {if(live)setFailed(true);}
    })();
    return ()=>{live=false;controller.abort();};
  },[saved,token,attempt]);
  if(failed)return <p role="alert">目前酒款與價格暫時無法確認；歷史結論仍保留。<button onClick={()=>setAttempt(value=>value+1)}>重新查詢目前價格</button></p>;
  if(!current)return <p>查詢目前酒款與價格中…</p>;
  const labels={within_budget:"符合當時保存的預算",over_budget:"超出當時預算",unknown:"價格資料不足，不能判為符合當時預算",not_filtered:"當時未設定價格篩選"};
  return <section aria-label="目前酒款與價格"><h3>目前酒款與價格</h3>
    <p>價格判定日期：{current.evaluatedOn}；使用當時保存的條件版本 {current.conditionsRevision}，預算 {current.budgetTwd ? `${current.budgetTwd} TWD` : "未設定"}。這次只重算價格資格，不是新的推薦。</p>
    {current.items.map(item=><div key={item.bottleVersionId}>
      {item.availability==="unresolved" ? <p>目前庫內無法解析此版本（{item.bottleVersionId}）；保留歷史選擇，不自動改指其他酒款。</p> : <>
        <p>{item.name}：{labels[item.budgetQualification]}。</p>
        {item.priceQualification==="unqualified" && <p>目前沒有符合價格政策的報價。</p>}
        {item.priceUpperBoundTwd!==null && <p>台灣參考價上緣：{item.priceUpperBoundTwd} TWD。</p>}
        {item.prices.map(price=><p key={price.id}>{price.amount} {price.currency}／{price.volumeMl} ml，{price.market}，查核日 {price.checkedOn}；<a href={price.sourceUrl} target="_blank" rel="noopener noreferrer">報價來源</a>。</p>)}
      </>}
    </div>)}
    <p>參考報價不代表即時庫存或可購買狀態。</p>
    <a href={`/plans/${saved.planId}?restartTaskId=${saved.taskId}`}>重新選擇探索方向</a>{" "}<a href="/catalog">查看目前已覆核酒款與來源</a>
    <button onClick={()=>setAttempt(value=>value+1)}>重新查詢目前價格</button>
  </section>;
}
