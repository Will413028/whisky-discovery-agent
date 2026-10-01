"use client";
import {useAuth0} from "@auth0/auth0-react";
import {useCallback,useEffect,useRef,useState} from "react";
import type {components} from "../../../../../contracts/api";
import validCatalog from "../../../../../contracts/catalog-view.validator.js";
import {listBottleFeedback,type BottleFeedback} from "./feedback-client";
import {BottleFeedbackEditor} from "./feedback-editor";
import {LongTermPreferencesEditor,type FeedbackPreferenceSource} from "./preferences-editor";
import {safeReturnTo} from "../identity";
type CatalogView=components["schemas"]["CatalogView"];
export function BottleFeedbackLibrary(){
  const auth=useAuth0();const [loginError,setLoginError]=useState(false);
  if(auth.isLoading)return <p>載入帳號中…</p>;
  if(!auth.isAuthenticated)return <><button onClick={()=>void auth.loginWithRedirect({appState:{returnTo:safeReturnTo(window.location.href,window.location.origin)}}).catch(()=>setLoginError(true))}>登入查看收藏與品飲回饋</button>{loginError && <p role="alert">暫時無法登入，請重試。</p>}</>;
  return <FeedbackSession key={auth.user?.sub}/>;
}
function FeedbackSession(){
  const {getAccessTokenSilently}=useAuth0();
  const token=useCallback(async()=>{const value=await getAccessTokenSilently();if(!value)throw new Error("AUTH_REQUIRED");return value;},[getAccessTokenSilently]);
  const [items,setItems]=useState<BottleFeedback[]|null>(null);
  const [catalog,setCatalog]=useState<CatalogView|null>(null);
  const [catalogError,setCatalogError]=useState(false);
  const [error,setError]=useState(false);
  const [busy,setBusy]=useState(false);
  const [cursor,setCursor]=useState<string|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [preferenceSource,setPreferenceSource]=useState<FeedbackPreferenceSource>();
  const epoch=useRef(0);
  const retryCursor=useRef<string|null>(null);
  async function load(next:string|null,current:number,signal?:AbortSignal){
    retryCursor.current=next;setBusy(true);setError(false);
    try {
      const access=await token();if(current!==epoch.current)return;
      const page=await listBottleFeedback(access,next,signal);if(current!==epoch.current)return;
      setItems(previous=>[...new Map([...(next ? previous ?? [] : []),...page.items].map(item=>[item.id,item])).values()]);setCursor(page.nextCursor);
    } catch {if(current===epoch.current)setError(true);}
    finally {if(current===epoch.current)setBusy(false);}
  }
  useEffect(()=>{
    const current=++epoch.current;const controller=new AbortController();
    setCatalog(null);setCatalogError(false);
    void load(null,current,controller.signal);
    void fetch("/api/v1/catalog",{cache:"no-store",signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error("CATALOG_UNAVAILABLE");
      const value:unknown=await response.json();if(!validCatalog(value))throw new Error("INVALID_RESPONSE");
      if(current===epoch.current)setCatalog(value);
    }).catch(()=>{if(current===epoch.current)setCatalogError(true);});
    return ()=>{++epoch.current;controller.abort();};
  },[token,refresh]);
  return <section aria-label="收藏與品飲回饋">
    <h2>收藏與品飲回饋</h2><p>收藏表示想探索；品飲感受不會自動變成長期風味偏好。取消收藏並改為尚未品飲、保存後，這筆紀錄會離開列表。</p>
    {catalog && <p>目前酒款與價格判定日期：{catalog.evaluatedOn}。參考報價不代表即時庫存。</p>}
    {catalogError && <p role="alert">目前酒款資料無法確認，仍保留已存回饋。</p>}
    {error && <p role="alert">暫時無法讀取收藏與品飲回饋。<button disabled={busy} onClick={()=>void load(retryCursor.current,epoch.current)}>重新讀取回饋</button></p>}
    {!items && !error && <p>正在讀取收藏與品飲回饋。</p>}
    {items?.length===0 && <p>尚未保存收藏或品飲回饋。</p>}
    {items?.map(item=>{
      const resolved=catalog?.items.find(value=>value.bottleVersionId===item.bottleVersionId);
      return <article key={item.id}><h3>{resolved?.name ?? `酒款版本 ${item.bottleVersionId}`}</h3>
        {catalog && !resolved && <p>目前庫內無法解析此版本，保留原紀錄，可取消收藏或重新選擇。</p>}
        {resolved && <><p>{resolved.versionLabel}</p><p>{resolved.priceUpperBoundTwd!==null ? `目前符合價格政策的台灣參考價上緣：${resolved.priceUpperBoundTwd} TWD。` : "目前沒有符合價格政策的報價。"}</p></>}
        <p>{item.wantToExplore ? "想探索" : "未收藏"}；{item.tasting==="liked" ? "喝過喜歡" : item.tasting==="disliked" ? "喝過不喜歡" : "尚未品飲"}</p>
        {item.tastingReason && <p>{item.tastingReason}</p>}
        <BottleFeedbackEditor version={item.bottleVersionId} name={resolved?.name ?? "未解析版本"} token={token}/>
        {item.tasting!=="not_tasted" && <button onClick={()=>setPreferenceSource({id:item.id,revision:item.revision,reason:item.tastingReason})}>從這筆回饋寫明確偏好</button>}
      </article>;
    })}
    {cursor && !error && <button disabled={busy} onClick={()=>void load(cursor,epoch.current)}>讀取更多回饋</button>}
    <LongTermPreferencesEditor token={token} source={preferenceSource}/>
    <button disabled={busy} onClick={()=>setRefresh(value=>value+1)}>更新列表與目前酒款</button>{" "}<a href="/catalog">查看目前已覆核酒款</a>{" "}<a href="/plans">重新選擇探索方向</a>
  </section>;
}
