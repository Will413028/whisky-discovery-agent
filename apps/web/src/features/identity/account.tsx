"use client";
import { useAuth0 } from "@auth0/auth0-react";
import { useEffect, useState } from "react";
import createClient from "openapi-fetch";
import type { paths } from "../../../../../contracts/api";
import { safeReturnTo } from "./return-to";

export function AccountPanel() {
  const auth = useAuth0();
  const [status, setStatus] = useState<"loading" | "ready" | "login" | "error">("loading");
  const [signedOut, setSignedOut] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const {isAuthenticated, getAccessTokenSilently} = auth;
  useEffect(() => {
    if (auth.error) window.history.replaceState({}, "", safeReturnTo(window.location.href, window.location.origin));
  }, [auth.error]);
  useEffect(() => {
    if (!isAuthenticated || signedOut) return;
    const controller = new AbortController();
    let current = true;
    setStatus("loading");
    void (async () => {
      try {
        const token = await getAccessTokenSilently();
        if (!current) return;
        const client = createClient<paths>({baseUrl: window.location.origin});
        const {data, response} = await client.GET("/api/v1/me", {
          headers: {Authorization: `Bearer ${token}`}, signal: controller.signal,
          cache: "no-store",
        });
        if (current) setStatus(response.status === 401 ? "login" : response.ok && data?.id ? "ready" : "error");
      } catch (error) {
        if (current) setStatus(typeof error === "object" && error !== null && "error" in error &&
          ["login_required", "consent_required", "interaction_required"].includes(String(error.error)) ? "login" : "error");
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [isAuthenticated, getAccessTokenSilently, signedOut, attempt]);
  const login = () => void auth.loginWithRedirect({ appState: {
    returnTo: safeReturnTo(window.location.href, window.location.origin),
  } }).catch(() => setStatus("error"));
  if (auth.isLoading) return <p>載入帳號中…</p>;
  if (!isAuthenticated || signedOut) return <><button onClick={login}>登入</button>{status === "error" && <p role="alert">暫時無法登入，請重試。</p>}</>;
  return <section>
    {status === "ready" && <p>帳號已連線</p>}
    {status === "loading" && <p>載入帳號中…</p>}
    {status === "login" && <button onClick={login}>重新登入</button>}
    {status === "error" && <><p role="alert">暫時無法讀取帳號。</p><button onClick={() => setAttempt(attempt + 1)}>重試</button></>}
    <button onClick={() => {
      setSignedOut(true);
      setStatus("loading");
      void auth.logout({logoutParams:{returnTo:window.location.origin}}).catch(() => setStatus("error"));
    }}>登出</button>
  </section>;
}
