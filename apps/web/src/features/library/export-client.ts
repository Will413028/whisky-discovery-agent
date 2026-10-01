import type {components} from "../../../../../contracts/api";
import validExport from "../../../../../contracts/account-export-view.validator.js";
export type AccountExport=components["schemas"]["AccountExportViewV1"];
const maximumBytes=8*1024*1024;
export async function readAccountExport(token:string,signal?:AbortSignal):Promise<Blob>{
  const options={cache:"no-store" as const,headers:{Authorization:`Bearer ${token}`},signal};
  const identity=await fetch("/api/v1/me",options);
  if(!identity.ok)throw new Error("AUTH_REQUIRED");
  const actor:unknown=await identity.json();
  if(!actor || typeof actor!=="object" || !("id" in actor) || typeof actor.id!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(actor.id))throw new Error("INVALID_RESPONSE");
  if(signal?.aborted)throw new Error("SESSION_CHANGED");
  const response=await fetch("/api/v1/library/export",options);
  if(!response.ok){
    let code="REQUEST_FAILED";
    try {const value:unknown=await response.json();if(value && typeof value==="object" && "code" in value && value.code==="EXPORT_TOO_LARGE")code="EXPORT_TOO_LARGE";}catch{}
    throw new Error(code);
  }
  const expectedSize=Number(response.headers.get("x-export-bytes"));
  if(response.headers.get("x-export-owner")!==actor.id ||
    response.headers.get("x-export-schema")!=="1" ||
    !/^[1-9][0-9]*$/.test(response.headers.get("x-export-generation") ?? "") ||
    !Number.isSafeInteger(expectedSize) || expectedSize<1 ||
    response.headers.get("content-type")?.split(";")[0]!=="application/json") {
    await response.body?.cancel();throw new Error("INVALID_RESPONSE");
  }
  // Native Blob storage avoids retaining all chunks and a second JSON object in JS.
  // Every row has already passed the server's closed Export V1 DTO validation.
  const file=await response.blob();
  if(signal?.aborted)throw new Error("SESSION_CHANGED");
  if(file.size!==expectedSize)throw new Error("INVALID_RESPONSE");
  if(file.size<=maximumBytes){
    const value:unknown=JSON.parse(await file.text());
    if(!validExport(value) || value.ownerId!==actor.id)throw new Error("INVALID_RESPONSE");
  }
  return file;
}
