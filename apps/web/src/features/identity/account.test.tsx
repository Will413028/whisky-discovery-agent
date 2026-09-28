import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AccountPanel } from "./account";
import { safeReturnTo } from "./return-to";

const state = vi.hoisted(() => ({
  isAuthenticated: false, isLoading: false, error: undefined as Error | undefined,
  loginWithRedirect: vi.fn().mockResolvedValue(undefined), logout: vi.fn().mockResolvedValue(undefined), getAccessTokenSilently: vi.fn(),
}));
vi.mock("@auth0/auth0-react", () => ({ useAuth0: () => state }));
afterEach(() => { cleanup(); state.isAuthenticated = false; state.error = undefined; window.history.replaceState({}, "", "/"); vi.clearAllMocks(); vi.unstubAllGlobals(); });

test("login preserves the page to return to", () => {
  render(<AccountPanel />);
  fireEvent.click(screen.getByRole("button", { name: "登入" }));
  expect(state.loginWithRedirect).toHaveBeenCalledWith({ appState: { returnTo: window.location.pathname + window.location.search + window.location.hash } });
});

test("verified account is loaded with an in-memory bearer and cleared on logout", async () => {
  state.isAuthenticated = true;
  state.getAccessTokenSilently.mockResolvedValue("fixture-token");
  const fetch = vi.fn().mockResolvedValue(Response.json({id:"00000000-0000-4000-8000-000000000001"}));
  vi.stubGlobal("fetch", fetch);
  render(<AccountPanel />);
  await screen.findByText("帳號已連線");
  const request = fetch.mock.calls[0][0] as Request;
  expect(request.headers.get("authorization")).toBe("Bearer fixture-token");
  fireEvent.click(screen.getByRole("button", {name:"登出"}));
  expect(screen.queryByText("帳號已連線")).toBeNull();
  expect(state.logout).toHaveBeenCalledWith({logoutParams:{returnTo:window.location.origin}});
});

test("expired session asks for explicit login", async () => {
  state.isAuthenticated = true;
  state.getAccessTokenSilently.mockRejectedValue({error:"login_required"});
  render(<AccountPanel />);
  await screen.findByRole("button", {name:"重新登入"});
});

test("logout fences a late private response", async () => {
  state.isAuthenticated = true;
  let resolve!: (token: string) => void;
  state.getAccessTokenSilently.mockReturnValue(new Promise<string>((done) => { resolve = done; }));
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<AccountPanel />);
  fireEvent.click(screen.getByRole("button", {name:"登出"}));
  await act(async () => resolve("late-token"));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByText("帳號已連線")).toBeNull();
});

test("retry never restores a consumed OAuth callback on refresh", () => {
  window.history.replaceState({}, "", "/account?code=used&state=used&error=access_denied&error_description=denied&view=saved#details");
  render(<AccountPanel />);
  fireEvent.click(screen.getByRole("button", {name:"登入"}));
  expect(state.loginWithRedirect).toHaveBeenCalledWith({appState:{returnTo:"/account?view=saved#details"}});
});

test("failed callback is removed before retry and refresh", () => {
  window.history.replaceState({}, "", "/account?error=access_denied&state=used&view=saved");
  state.error = new Error("fixture failure");
  render(<AccountPanel />);
  expect(window.location.search).toBe("?view=saved");
});

test("return target rejects external URLs and malformed URLs", () => {
  expect(safeReturnTo("https://other.example/", window.location.origin)).toBe("/account");
  expect(safeReturnTo("http://[", window.location.origin)).toBe("/account");
  expect(safeReturnTo("/account?code=used&state=used&view=saved", window.location.origin)).toBe("/account?view=saved");
});
