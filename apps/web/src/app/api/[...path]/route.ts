import { env } from "cloudflare:workers";
import { proxy, type PrivateAPI } from "../../../features/identity/proxy";

function forward(request: Request) {
  const binding = (env as unknown as { WHISKY_API?: PrivateAPI }).WHISKY_API;
  return proxy(request, binding);
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
