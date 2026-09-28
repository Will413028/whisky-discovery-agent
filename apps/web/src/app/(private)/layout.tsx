import type { ReactNode } from "react";
import { IdentityProvider } from "../../features/identity";

export default function PrivateLayout({children}: {children: ReactNode}) {
  return <IdentityProvider>{children}</IdentityProvider>;
}
