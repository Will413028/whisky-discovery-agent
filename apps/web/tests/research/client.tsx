/** Browser fixture runs the product research components against a synthetic API. */
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ResearchStart, ResearchTask } from "../../src/features/research/ui";
import {PlanDetail, Plans} from "../../src/features/discovery/ui";

function App() {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    const changed = () => setPath(location.pathname);
    addEventListener("popstate", changed);
    return () => removeEventListener("popstate", changed);
  }, []);
  const taskId = /^\/research\/([0-9a-f-]{36})$/.exec(path)?.[1];
  const planId = /^\/plans\/([0-9a-f-]{36})$/.exec(path)?.[1];
  const proposalTaskId=new URLSearchParams(window.location.search).get("proposalTaskId") ?? undefined;
  return <main><h1>合成研究流程驗收</h1>{planId ? <PlanDetail planId={planId} proposalTaskId={proposalTaskId} /> : path === "/plans" ? <Plans /> : taskId ? <ResearchTask taskId={taskId} /> : <ResearchStart />}</main>;
}

createRoot(document.getElementById("fixture")!).render(<App />);
