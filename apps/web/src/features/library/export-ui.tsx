"use client";
import {useEffect,useRef,useState} from "react";
import {readAccountExport} from "./export-client";
export function AccountExportButton({token}:{token:()=>Promise<string>}){
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
  const epoch=useRef(0);const active=useRef<AbortController|null>(null);
  useEffect(()=>{
    ++epoch.current;setBusy(false);setMessage("");
    return ()=>{++epoch.current;active.current?.abort();};
  },[token]);
  async function download(){
    const current=epoch.current;const controller=new AbortController();active.current=controller;
    setBusy(true);setMessage("");
    try {
      const access=await token();if(current!==epoch.current)return;
      const value=await readAccountExport(access,controller.signal);if(current!==epoch.current)return;
      const url=URL.createObjectURL(new Blob([JSON.stringify(value)],{type:"application/json"}));
      const anchor=document.createElement("a");anchor.href=url;anchor.download="whisky-account.json";
      const revoke=URL.revokeObjectURL.bind(URL);anchor.click();setTimeout(()=>revoke(url),1000);
      setMessage("匯出檔已準備，瀏覽器會下載。");
    }catch(error){if(current===epoch.current)setMessage(error instanceof Error && error.message==="EXPORT_TOO_LARGE" ? "資料量超過目前單次匯出上限，未下載不完整檔案。" : "暫時無法匯出資料，請稍後重試。");}
    finally {if(current===epoch.current){setBusy(false);active.current=null;}}
  }
  return <section aria-label="我的資料匯出"><h2>匯出我的資料</h2><p>下載自己的探索、報告、結論、回饋與偏好；匯出檔不能代替備份。</p><button disabled={busy} onClick={()=>void download()}>{busy ? "準備匯出中…" : "匯出我的資料"}</button>{message && <p role="status">{message}</p>}</section>;
}
