export function useRouter() {
  return {push(path: string) {history.pushState({}, "", path); dispatchEvent(new PopStateEvent("popstate"));}};
}
