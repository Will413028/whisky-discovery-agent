import {SavedConclusionsEntry} from "../../../../../features/library";

export default async function Conclusions({params}:{params:Promise<{planId:string}>}) {
  const {planId}=await params;
  return <main><h1>保存的探索結論</h1><SavedConclusionsEntry planId={planId}/><a href={`/plans/${planId}`}>回到探索計畫</a></main>;
}
