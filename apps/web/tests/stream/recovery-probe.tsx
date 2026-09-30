/** Temporary T09 live acceptance UI. Uses the real API and memory-only tokens. */
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import { createPlan, readTask, startResearch } from "../../src/features/research/client";

type Case = { actor: string; planId: string; taskId: string; revision: number; cancelKey: string; changeKey: string };
const storageKey = "whisky-t09-live-case";
const questionGoal = "我喝過格蘭菲迪但不確定是 12 年常規版還是 15 年 Solera，想先確認版本再比較下一款的風味差異";

function Probe() {
  const auth = useAuth0();
  const [testCase, setTestCase] = useState<Case | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(storageKey) ?? "null") as Case | null; }
    catch { return null; }
  });
  const [result, setResult] = useState<object>({ status: "idle" });
  const [busy, setBusy] = useState(false);
  const [actor, setActor] = useState("");
  const [targetTask, setTargetTask] = useState("");
  const [targetPlan, setTargetPlan] = useState("");
  const [targetReport, setTargetReport] = useState("");
  const accessToken = async () => {
    const token = await auth.getAccessTokenSilently();
    if (!token) throw new Error("missing-token");
    return token;
  };
  const run = (action: () => Promise<void>) => {
    setBusy(true);
    void action().catch(() => setResult({ status: "request-failed" })).finally(() => setBusy(false));
  };
  const request = async (path: string, body?: object) => {
    const token = await accessToken();
    const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const value = await response.json();
    return { http: response.status, cache: response.headers.get("cache-control"), value };
  };
  const identify = async () => {
    const response = await request("/api/v1/me");
    if (response.http !== 200 || typeof response.value?.id !== "string") throw new Error("identity");
    setActor(response.value.id);
    return response.value.id as string;
  };
  const ownCase = async () => {
    if (!testCase || await identify() !== testCase.actor) throw new Error("wrong-owner");
    return testCase;
  };
  const seed = async () => {
    const owner = await identify();
    const token = await accessToken();
    const plan = await createPlan(token, crypto.randomUUID(), questionGoal, null);
    const task = await startResearch(token, plan, crypto.randomUUID(), crypto.randomUUID(), crypto.randomUUID());
    const next = { actor: owner, planId: plan.id, taskId: task.taskId, revision: 1,
      cancelKey: crypto.randomUUID(), changeKey: crypto.randomUUID() };
    sessionStorage.setItem(storageKey, JSON.stringify(next));
    setTestCase(next);
    setResult({ status: "created", planId: plan.id, taskId: task.taskId, taskStatus: task.status });
  };
  const read = async () => {
    const current = await ownCase();
    const token = await accessToken();
    const task = await readTask(current.taskId, token);
    const plan = await request(`/api/v1/plans/${current.planId}`);
    setResult({ status: "read", taskId: task.taskId, taskStatus: task.status, viewVersion: task.viewVersion,
      reportId: task.reportId, waitingVersion: task.question?.waitingVersion,
      planHttp: plan.http, revision: plan.value.conditionsRevision, cache: plan.cache });
  };
  const command = async (kind: "cancel" | "change") => {
    const current = await ownCase();
    const response = kind === "cancel"
      ? await request(`/api/v1/tasks/${current.taskId}/cancel`, { key: current.cancelKey })
      : await request(`/api/v1/plans/${current.planId}/conditions`, { key: current.changeKey, expectedRevision: 1,
        conditions: { schema_version: 1, entry: "beginner", goal: "找帶果香的酒款，保持 TWD 1000 嚴格上限", budget_twd: "1000" } });
    setResult({ status: "control", http: response.http, cache: response.cache, commandId: response.value.id,
      kind: response.value.kind, receiptStatus: response.value.status, result: response.value.result });
  };
  const isolation = async () => {
    await identify();
    const ids = [["task", targetTask], ["plan", targetPlan], ["report", targetReport]] as const;
    const checks = [];
    for (const [kind, id] of ids) {
      if (!/^[0-9a-f-]{36}$/.test(id)) continue;
      const response = await request(`/api/v1/${kind}s/${id}`);
      checks.push({ kind, http: response.http, cache: response.cache });
    }
    setResult({ status: "isolation", checks });
  };
  if (auth.isLoading) return <p>載入測試帳號…</p>;
  return <main><h1>T09 正式 API 驗收頁</h1>
    <p>僅建立本次驗收紀錄；使用真實 reviewed catalog，沒有合成 API。Token 只留記憶體，不輸出。</p>
    {!auth.isAuthenticated ? <button onClick={() => void auth.loginWithRedirect({ appState: { returnTo: "/__recovery_probe.html" } })}>登入驗收帳號</button> : <>
      <button disabled={busy} onClick={() => run(async () => { await identify(); setResult({ status: "identified" }); })}>核對帳號</button>
      <p>Actor：<output>{actor}</output></p>
      <button disabled={busy} onClick={() => run(seed)}>建立版本等待案例</button>
      <button disabled={busy || !testCase} onClick={() => run(read)}>讀取本次案例</button>
      <button disabled={busy || !testCase} onClick={() => run(() => command("cancel"))}>取消本次案例（重按沿用同 key）</button>
      <button disabled={busy || !testCase} onClick={() => run(() => command("change"))}>改版本條件（重按沿用同 key）</button>
      <p>本次案例：{JSON.stringify(testCase)}</p>
      <label>另一帳號 Task UUID<input value={targetTask} onChange={e => setTargetTask(e.target.value)} /></label>
      <label>另一帳號 Plan UUID<input value={targetPlan} onChange={e => setTargetPlan(e.target.value)} /></label>
      <label>另一帳號 Report UUID<input value={targetReport} onChange={e => setTargetReport(e.target.value)} /></label>
      <button disabled={busy} onClick={() => run(isolation)}>驗證隔離</button>
      <button disabled={busy} onClick={() => void auth.loginWithRedirect({ appState: { returnTo: "/__recovery_probe.html" }, authorizationParams: {
        connection: "google-oauth2", prompt: "select_account" } })}>切換 Google 驗收帳號</button>
    </>}
    <pre aria-label="measurement">{JSON.stringify(result, null, 2)}</pre>
  </main>;
}

createRoot(document.getElementById("probe")!).render(<Auth0Provider
  domain={process.env.NEXT_PUBLIC_AUTH0_DOMAIN!} clientId={process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID!}
  cacheLocation="memory" useRefreshTokens={false}
  authorizationParams={{ audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE, redirect_uri: `${location.origin}/account` }}
  onRedirectCallback={() => history.replaceState({}, "", "/__recovery_probe.html")}><Probe /></Auth0Provider>);
