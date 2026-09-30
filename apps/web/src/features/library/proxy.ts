import {forwardPrivate,privateFailure,type PrivateAPI} from "../../shared/api/private-forward";

export async function libraryProxy(request:Request,upstream?:PrivateAPI):Promise<Response> {
  const url=new URL(request.url);
  const collection=url.pathname==="/api/v1/library/conclusions";
  const resource=/^\/api\/v1\/library\/conclusions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url.pathname);
  const context=/^\/api\/v1\/library\/reports\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/conclusion-context$/.test(url.pathname);
  const revisit=/^\/api\/v1\/library\/conclusions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/revisit$/.test(url.pathname);
  if(!collection && !resource && !context && !revisit) return privateFailure(404,"NOT_FOUND");
  if(request.method!=="GET" && !(collection && request.method==="POST")) return privateFailure(405,"METHOD_NOT_ALLOWED");
  if(url.search && !(collection && request.method==="GET")) return privateFailure(404,"NOT_FOUND");
  for(const key of url.searchParams.keys()) {
    if(!["planId","limit","cursor"].includes(key)) return privateFailure(404,"NOT_FOUND");
    if(url.searchParams.getAll(key).length!==1) return privateFailure(422,"INVALID_REQUEST");
  }
  return forwardPrivate(request,upstream);
}
