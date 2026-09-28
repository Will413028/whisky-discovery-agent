import { useSyncExternalStore, type ReactNode } from "react";

export function Auth0Provider({children}: {children: ReactNode}) {return children;}

let signedIn = false;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => {listeners.add(listener); return () => {listeners.delete(listener);};};
const snapshot = () => signedIn;
const loginWithRedirect = async () => {signedIn = true; listeners.forEach(listener => listener());};
const getAccessTokenSilently = async () => signedIn ? "synthetic-research-token" : undefined;

export function useAuth0() {
  const isAuthenticated = useSyncExternalStore(subscribe, snapshot, snapshot);
  return {
    isAuthenticated, isLoading:false,
    loginWithRedirect, getAccessTokenSilently,
  };
}
