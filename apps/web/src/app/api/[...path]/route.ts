import { proxy } from "../../../features/identity/proxy";
import { apiUpstream } from "../../../shared/api/upstream.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function forward(request: Request) {
  return proxy(request, apiUpstream(process.env.WHISKY_API_ORIGIN));
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
