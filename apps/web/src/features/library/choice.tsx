"use client";
import {useState} from "react";
import {saveConclusion,ConclusionRejected,type SaveConclusion} from "./client";

export function ConclusionChoice({planId,reportId,revision,candidates,getToken}:{planId:string;reportId:string;revision:number;candidates:{versionId:string;name:string}[];getToken:()=>Promise<string>}) {
  const [selected,setSelected]=useState<string|null>(null);
  const [reason,setReason]=useState("");
  const [tradeoff,setTradeoff]=useState("");
  const [attempt,setAttempt]=useState<SaveConclusion|null>(null);
  const [busy,setBusy]=useState(false);
  const [saved,setSaved]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [rejected,setRejected]=useState<ConclusionRejected|null>(null);
  async function submit(event:React.FormEvent) {
    event.preventDefault();
    if(busy || saved || rejected || (!attempt && (selected===null || !reason.trim()))) return;
    const command=attempt ?? {schemaVersion:1,key:crypto.randomUUID(),planId,reportId,expectedConditionsRevision:revision,selectedVersionId:selected==="none" ? null : selected,reason:reason.trim(),tradeoff:tradeoff.trim()};
    setAttempt(command);setBusy(true);setError(null);
    try {await saveConclusion(command,await getToken());setSaved(true);}
    catch(error) {
      if(error instanceof ConclusionRejected) setRejected(error);
      else setError("保存暫時無法確認，請重送同一結論。");
    }
    finally {setBusy(false);}
  }
  return <section><h2>保存這次探索結論</h2><p>這是本次選擇；收藏與喝過回饋另行記錄。</p>
    {saved ? <p>探索結論已保存。</p> : <form onSubmit={submit}>
      <fieldset disabled={busy || attempt!==null}><legend>這次想探索哪一支？</legend>
        {candidates.map(candidate=><label key={candidate.versionId}><input type="radio" name="conclusion" value={candidate.versionId} checked={selected===candidate.versionId} onChange={()=>setSelected(candidate.versionId)}/>{candidate.name}</label>)}
        <label><input type="radio" name="conclusion" value="none" checked={selected==="none"} onChange={()=>setSelected("none")}/>這次沒有適合的</label>
        <label>選擇理由<textarea value={reason} maxLength={2000} onChange={event=>setReason(event.target.value)}/></label>
        <label>取捨<textarea value={tradeoff} maxLength={2000} onChange={event=>setTradeoff(event.target.value)}/></label>
      </fieldset>
      {error && <p role="alert">{error}</p>}
      {rejected ? <p role="alert">
        {rejected.code==="AUTH_REQUIRED" || rejected.code==="IDENTITY_CHANGED" ? <>登入身份已失效，請重新登入後確認結論。<a href="/account">重新確認帳號</a></>
          : rejected.code==="NOT_FOUND" ? <>報告或計畫已無法使用。<a href="/plans">查看其他探索計畫</a></>
          : <>{rejected.code==="REVISION_CONFLICT" ? "計畫條件已變更，請先確認目前條件。" : "這筆結論已被拒絕，請重新確認資料。"}<a href={`/plans/${planId}`}>回到目前探索計畫</a></>}
      </p> : <button disabled={busy || (!attempt && (selected===null || !reason.trim()))}>{busy ? "保存中…" : attempt ? "重送同一結論" : "保存探索結論"}</button>}
    </form>}
  </section>;
}
