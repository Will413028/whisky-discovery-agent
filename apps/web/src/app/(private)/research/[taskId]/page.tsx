import { ResearchTaskEntry } from "../../../../features/research/ui";

export default async function Task({params}: {params:Promise<{taskId:string}>}) {
  const {taskId} = await params;
  return <main><h1>探索進度</h1><ResearchTaskEntry taskId={taskId} /></main>;
}
