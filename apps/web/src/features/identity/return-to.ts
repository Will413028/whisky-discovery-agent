export function safeReturnTo(value: string | undefined, origin: string): string {
  try {
    const target = new URL(value || "/account", origin);
    if (target.origin !== origin) return "/account";
    for (const key of ["code", "state", "error", "error_description", "error_uri"]) {
      target.searchParams.delete(key);
    }
    return target.pathname + target.search + target.hash;
  } catch {
    return "/account";
  }
}
