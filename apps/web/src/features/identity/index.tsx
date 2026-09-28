"use client";
import { Auth0Provider } from "@auth0/auth0-react";
import { useEffect, useState } from "react";
import { AccountPanel } from "./account";
import { safeReturnTo } from "./return-to";

export function IdentityEntry() {
  const [origin, setOrigin] = useState<string>();
  useEffect(() => setOrigin(window.location.origin), []);
  const domain = process.env.NEXT_PUBLIC_AUTH0_DOMAIN;
  const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID;
  const audience = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE;
  if (!domain || !clientId || !audience) return <p>帳號功能準備中。</p>;
  if (!origin) return <p>載入帳號中…</p>;
  return <Auth0Provider domain={domain} clientId={clientId}
    cacheLocation="memory" useRefreshTokens={false}
    authorizationParams={{redirect_uri: `${origin}/account`, audience}}
    onRedirectCallback={(state) => {
      window.history.replaceState({}, "", safeReturnTo(state?.returnTo, origin));
    }}>
    <AccountPanel />
  </Auth0Provider>;
}
