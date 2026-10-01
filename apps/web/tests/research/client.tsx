/** Browser fixture runs the product research components against a synthetic API. */
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ResearchStart, ResearchTask } from "../../src/features/research/ui";
import {PlanDetail, Plans} from "../../src/features/discovery/ui";
import {BottleFeedbackLibrary,SavedConclusions} from "../../src/features/library";

function App() {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    const changed = () => setPath(location.pathname);
    addEventListener("popstate", changed);
    return () => removeEventListener("popstate", changed);
  }, []);
  const taskId = /^\/research\/([0-9a-f-]{36})$/.exec(path)?.[1];
  const planId = /^\/plans\/([0-9a-f-]{36})$/.exec(path)?.[1];
  const conclusionsPlanId=/^\/plans\/([0-9a-f-]{36})\/conclusions$/.exec(path)?.[1];
  const proposalTaskId=new URLSearchParams(window.location.search).get("proposalTaskId") ?? undefined;
  const restartTaskId=new URLSearchParams(window.location.search).get("restartTaskId") ?? undefined;
  return <main><h1>合成研究流程驗收</h1>{new URLSearchParams(window.location.search).get("library")==="1" ? <BottleFeedbackLibrary/> : conclusionsPlanId ? <SavedConclusions planId={conclusionsPlanId}/> : planId ? <PlanDetail planId={planId} proposalTaskId={proposalTaskId} restartTaskId={restartTaskId} /> : path === "/plans" ? <Plans /> : taskId ? <ResearchTask taskId={taskId} /> : <ResearchStart />}</main>;
}

createRoot(document.getElementById("fixture")!).render(<App />);
