// @vitest-environment node
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { RunAgentInputSchema, RunFinishedEventSchema } from "@ag-ui/core";
import { expect, test } from "vitest";

const root = fileURLToPath(new URL("../../../", import.meta.url));
function python(source: string, input?: string): unknown {
  return JSON.parse(execFileSync("uv", ["run", "--project", `${root}backend`, "python", "-c", source], {
    cwd: root, encoding: "utf8", input, timeout: 15_000,
  }));
}

test("Python interrupt survives TypeScript parsing and returns through Python", () => {
  const wire = python(`from whisky.modules.research.public import waiting_event
print(waiting_event("fixture-thread", "fixture-run-1", "fixture-question").model_dump_json(by_alias=True, exclude_none=True))`);
  const parsed = RunFinishedEventSchema.parse(wire);
  expect(parsed.outcome).toEqual({type:"interrupt", interrupts:[{id:"fixture-question", reason:"input_required"}]});
  const returned = python(`import sys
from ag_ui.core import RunFinishedEvent
print(RunFinishedEvent.model_validate_json(sys.stdin.read()).model_dump_json(by_alias=True, exclude_none=True))`, JSON.stringify(parsed));
  expect(returned).toEqual(wire);
}, 30_000);

test("new-run resume survives Python validation and returns through TypeScript", () => {
  const input = RunAgentInputSchema.parse({
    threadId:"fixture-thread", runId:"fixture-run-2", state:{}, messages:[], tools:[], context:[], forwardedProps:{},
    resume:[{interruptId:"fixture-question", status:"resolved", payload:{answer:"fixture only"}}],
  });
  const returned = python(`import sys
from ag_ui.core import RunAgentInput
print(RunAgentInput.model_validate_json(sys.stdin.read()).model_dump_json(by_alias=True, exclude_none=True))`, JSON.stringify(input));
  expect(RunAgentInputSchema.parse(returned)).toEqual(input);
}, 30_000);

test("both SDK schemas reject an interrupt without a question", () => {
  const value = {type:"RUN_FINISHED", threadId:"fixture-thread", runId:"fixture-run", outcome:{type:"interrupt", interrupts:[]}};
  expect(RunFinishedEventSchema.safeParse(value).success).toBe(false);
  const result = python(`import sys, json
from ag_ui.core import RunFinishedEvent
from pydantic import ValidationError
try:
    RunFinishedEvent.model_validate_json(sys.stdin.read())
    print(json.dumps({"rejected": False}))
except ValidationError:
    print(json.dumps({"rejected": True}))`, JSON.stringify(value));
  expect(result).toEqual({rejected:true});
}, 30_000);
