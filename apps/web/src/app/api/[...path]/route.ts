import { proxy } from "../../../features/identity/proxy";
import { planProxy } from "../../../features/discovery/proxy";
import { researchReadProxy } from "../../../features/research/proxy";
import { apiUpstream } from "../../../shared/api/upstream.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function forward(request: Request) {
  const pathname = new URL(request.url).pathname;
  const adapter = pathname === "/api/v1/plans" || pathname.startsWith("/api/v1/plans/") ? planProxy
    : pathname.startsWith("/api/v1/tasks/") || pathname.startsWith("/api/v1/commands/") ? researchReadProxy : proxy;
  return adapter(request, apiUpstream(process.env.WHISKY_API_ORIGIN));
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
