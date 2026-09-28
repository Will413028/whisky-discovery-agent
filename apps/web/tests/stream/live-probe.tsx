/** Explicit, temporary T02 diagnostics. Never imported by the product app. */
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import { observeTask } from "../../src/features/research/observe";
import type { ResearchState } from "../../src/features/research/state";

const initial: ResearchState = {
  taskId:"00000000-0000-4000-8000-000000000001", threadId:"00000000-0000-4000-8000-000000000002",
  conditionsRevision:1, connection:0, view:null, connected:false,
};
const pageErrors: string[] = [];
window.addEventListener("error", () => pageErrors.push("pageerror"));
window.addEventListener("unhandledrejection", () => pageErrors.push("unhandledrejection"));

function Probe() {
  const auth = useAuth0();
  const active = useRef<AbortController | null>(null);
  const [result, setResult] = useState<object>({status:"idle"});
  const [actor, setActor] = useState("");
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (!auth.isAuthenticated) active.current?.abort();
  }, [auth.isAuthenticated]);
  const identify = async () => {
    const token = await auth.getAccessTokenSilently();
    const response = await fetch("/api/v1/me", {headers:{Authorization:`Bearer ${token}`}, cache:"no-store"});
    const body = await response.json();
    setActor(response.ok && typeof body === "object" && body !== null && "id" in body
      && typeof body.id === "string" ? body.id : `HTTP ${response.status}`);
  };
  const start = () => {
    active.current?.abort();
    const abort = new AbortController();
    active.current = abort;
    const started = performance.now();
    const snapshots: {version:number; atMs:number}[] = [];
    const requests: {status:number; atMs:number}[] = [];
    let lastVersion = 0;
    let state = initial;
    const render = (status: string) => setResult({status, connection:state.connection,
      connected:state.connected, taskStatus:state.view?.status, version:state.view?.viewVersion,
      elapsedMs:Math.round(performance.now()-started), snapshots, requests, pageErrors});
    void observeTask({initial, runId:"00000000-0000-4000-8000-000000000004",
      token:async()=>{
        const token=await auth.getAccessTokenSilently();
        if (!token) throw new Error("Missing access token");
        return token;
      }, signal:abort.signal, random:Math.random,
      fetch:async (...args) => {
        const response = await fetch(...args);
        requests.push({status:response.status, atMs:Math.round(performance.now()-started)});
        return response;
      },
      sleep:(milliseconds, signal)=>new Promise((resolve,reject)=>{
        if(signal.aborted) {reject(signal.reason); return;}
        const cancelled=()=>{clearTimeout(timer); reject(signal.reason);};
        const timer=setTimeout(()=>{signal.removeEventListener("abort",cancelled); resolve();},milliseconds);
        signal.addEventListener("abort",cancelled,{once:true});
      }),
      onState:next=>{
        state=next;
        if(next.view && next.view.viewVersion>lastVersion) {
          lastVersion=next.view.viewVersion;
          snapshots.push({version:lastVersion,atMs:Math.round(performance.now()-started)});
        }
        if(active.current===abort) render("observing");
      },
    }).then(()=>{if(active.current===abort) render("stopped");})
      .catch(error=>{if(active.current===abort) render(`error:${error.code ?? "unknown"}`);});
  };
  if (auth.isLoading) return <p>載入登入狀態…</p>;
  return <main><h1>T02 合成入口測試，非產品資料</h1>
    {!auth.isAuthenticated ? <button onClick={()=>void auth.loginWithRedirect()}>登入測試帳號</button> : <>
      <button onClick={()=>void identify().catch(()=>setActor("identity failed"))}>核對帳號</button>
      <p>Actor: <output aria-label="actor">{actor}</output></p>
      <button onClick={start}>開始觀察合成資料</button>
      <button onClick={()=>active.current?.abort()}>停止觀察</button>
      <button onClick={()=>{
        active.current?.abort(); active.current=null; setActor(""); setResult({status:"signed-out"});
        void auth.logout({logoutParams:{returnTo:location.origin}});
      }}>登出並清除測試狀態</button>
    </>}
    <pre aria-label="measurement">{JSON.stringify(result,null,2)}</pre>
  </main>;
}

createRoot(document.getElementById("probe")!).render(<Auth0Provider
  domain={process.env.NEXT_PUBLIC_AUTH0_DOMAIN!} clientId={process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID!}
  cacheLocation="memory" useRefreshTokens={false}
  authorizationParams={{audience:process.env.NEXT_PUBLIC_AUTH0_AUDIENCE,
    redirect_uri:`${location.origin}/__entry_probe.html`}}
  onRedirectCallback={()=>history.replaceState({},"","/__entry_probe.html")}>
  <Probe />
</Auth0Provider>);
