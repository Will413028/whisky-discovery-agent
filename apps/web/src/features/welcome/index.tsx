"use client";

import { useState } from "react";

export function Welcome() {
  const [expanded, setExpanded] = useState(false);
  return <section>
    <button type="button" aria-expanded={expanded} aria-controls="exploration-intro"
      onClick={() => setExpanded(!expanded)}>
      了解探索方式
    </button>
    <p id="exploration-intro" hidden={!expanded}>
      從喜歡的風味或酒款出發，找出下一支想探索的威士忌。
    </p>
  </section>;
}
