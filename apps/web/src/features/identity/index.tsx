"use client";
import { Auth0Provider } from "@auth0/auth0-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { AccountPanel } from "./account";
import { safeReturnTo } from "./return-to";
export { safeReturnTo } from "./return-to";

export function IdentityProvider({children}: {children: ReactNode}) {
  const router = useRouter();
  const [origin, setOrigin] = useState<string>();
  useEffect(() => setOrigin(window.location.origin), []);
  const domain = process.env.NEXT_PUBLIC_AUTH0_DOMAIN;
  const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID;
  const audience = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE;
  if (!domain || !clientId || !audience) return children;
  if (!origin) return <p>載入帳號中…</p>;
  return <Auth0Provider domain={domain} clientId={clientId}
    cacheLocation="memory" useRefreshTokens={false}
    authorizationParams={{redirect_uri: `${origin}/account`, audience}}
    onRedirectCallback={(state) => {
      router.replace(safeReturnTo(state?.returnTo, origin));
    }}>
    {children}
  </Auth0Provider>;
}

export function IdentityEntry() {
  if (!process.env.NEXT_PUBLIC_AUTH0_DOMAIN || !process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ||
      !process.env.NEXT_PUBLIC_AUTH0_AUDIENCE) return <p>帳號功能準備中。</p>;
  return <AccountPanel />;
}
