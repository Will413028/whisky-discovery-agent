"use client";
import {useAuth0} from "@auth0/auth0-react";
import {useEffect,useRef,useState} from "react";
import {listConclusions,type Conclusion} from "./client";
import {safeReturnTo} from "../identity";

export function SavedConclusionsEntry({planId}:{planId:string}) {
  if(!process.env.NEXT_PUBLIC_AUTH0_DOMAIN || !process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID || !process.env.NEXT_PUBLIC_AUTH0_AUDIENCE) return <p>帳號功能準備中。</p>;
  return <SavedConclusions planId={planId}/>;
}

export function SavedConclusions({planId}:{planId:string}) {
  const auth=useAuth0();
  const [loginError,setLoginError]=useState(false);
  if(auth.isLoading) return <p>載入帳號中…</p>;
  if(!auth.isAuthenticated) return <><button onClick={()=>void auth.loginWithRedirect({appState:{returnTo:safeReturnTo(window.location.href,window.location.origin)}}).catch(()=>setLoginError(true))}>登入查看保存結論</button>{loginError && <p role="alert">暫時無法登入，請重試。</p>}</>;
  return <SavedSession key={JSON.stringify([planId,auth.isAuthenticated,auth.user?.sub])} planId={planId}/>;
}
function SavedSession({planId}:{planId:string}) {
  const auth=useAuth0();
  const [items,setItems]=useState<Conclusion[]|null>(null);
  const [cursor,setCursor]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(false);
  const life=useRef(0);
  const {isAuthenticated,getAccessTokenSilently}=auth;
  async function load(next:string|null,generation:number,signal?:AbortSignal) {
    setBusy(true);setError(false);
    try {
      const token=await getAccessTokenSilently();
      if(generation!==life.current) return;
      if(!token) throw new Error("AUTH_REQUIRED");
      const page=await listConclusions(planId,token,next,signal);
      if(generation!==life.current) return;
      setItems(previous=>[...new Map([...(next ? previous ?? [] : []),...page.items].map(item=>[item.id,item])).values()]);setCursor(page.nextCursor);
    } catch {if(generation===life.current)setError(true);}
    finally {if(generation===life.current)setBusy(false);}
  }
  useEffect(()=>{
    const generation=++life.current;
    if(!isAuthenticated) return;
    const controller=new AbortController();void load(null,generation,controller.signal);
    return ()=>{life.current++;controller.abort();};
  },[isAuthenticated,getAccessTokenSilently,planId]);
  if(!isAuthenticated || auth.isLoading) return null;
  return <section aria-label="保存的探索結論"><h2>歷史結論</h2><p>未重新查詢前，不代表仍符合目前預算或價格。</p>
    {error && <p role="alert">暫時無法讀取保存結論。<button disabled={busy} onClick={()=>void load(cursor,life.current)}>重新讀取結論</button></p>}
    {!items && !error && <p>讀取保存結論中…</p>}
    {items?.length===0 && <p>尚未保存探索結論。</p>}
    {items?.map(item=><article key={item.id}><p>{item.outcome==="no_suitable" ? "這次沒有適合的" : "已選擇下一支想探索的酒"}；條件版本 {item.conditionsRevision}</p>
      {item.selectedBottleName && <p>當時選擇：{item.selectedBottleName}</p>}
      <time dateTime={item.createdAt}>{item.createdAt}</time><p>{item.reason}</p>{item.tradeoff && <p>取捨：{item.tradeoff}</p>}
      <p>當時條件：{item.conditions.goal}</p><a href={`/research/${item.taskId}`}>查看當時報告與來源</a>
    </article>)}
    {cursor && !error && <button disabled={busy} onClick={()=>void load(cursor,life.current)}>讀取更多結論</button>}
  </section>;
}
