import type {components} from "../../../../../contracts/api";
import validExport from "../../../../../contracts/account-export-view.validator.js";
export type AccountExport=components["schemas"]["AccountExportViewV1"];
const maximumBytes=8*1024*1024;
export async function readAccountExport(token:string,signal?:AbortSignal):Promise<AccountExport>{
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
  const reader=response.body?.getReader();
  if(!reader)throw new Error("INVALID_RESPONSE");
  const chunks:Uint8Array[]=[];let size=0;
  try {
    for(;;){
      const {done,value}=await reader.read();if(done)break;
      size+=value.byteLength;
      if(size>maximumBytes){await reader.cancel();throw new Error("EXPORT_TOO_LARGE");}
      chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  const value:unknown=JSON.parse(new TextDecoder().decode(bytes));
  if(!validExport(value) || value.ownerId!==actor.id)throw new Error("INVALID_RESPONSE");
  return value;
}
