import {PlanDetailEntry} from "../../../../features/discovery/ui";

export default async function Plan({params}: {params:Promise<{planId:string}>}) {
  const {planId} = await params;
  return <main><h1>探索計畫</h1><PlanDetailEntry planId={planId} /></main>;
}
