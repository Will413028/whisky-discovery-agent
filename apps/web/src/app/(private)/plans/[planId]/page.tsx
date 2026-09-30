import {PlanDetailEntry} from "../../../../features/discovery/ui";

export default async function Plan({params,searchParams}: {params:Promise<{planId:string}>;searchParams:Promise<{proposalTaskId?:string | string[]}>}) {
  const {planId} = await params;
  const query=await searchParams;
  const proposalTaskId=typeof query.proposalTaskId === "string" ? query.proposalTaskId : undefined;
  return <main><h1>探索計畫</h1><PlanDetailEntry planId={planId} proposalTaskId={proposalTaskId} /></main>;
}
