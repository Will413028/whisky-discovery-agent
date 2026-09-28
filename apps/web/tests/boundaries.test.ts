// @vitest-environment node
import { expect, test } from "vitest";
import { violations } from "../scripts/check-boundaries";

test.each([
  'import { X } from "@/features/research";',
  'export { X } from "../../features/research";',
  'const load = () => import("@/features/research");',
])("shared cannot depend on a feature: %s", (source) => {
  expect(violations(source, "/web/src/shared/ui/card.ts", "/web/src")).not.toEqual([]);
});

test("app may compose public features", () => {
  expect(violations('import { X } from "@/features/research";', "/web/src/app/page.tsx", "/web/src")).toEqual([]);
});

test.each([
  'import { X } from "@/features/catalog/internal";',
  'import { X } from "../catalog/internal";',
])("features cannot reach into other features: %s", (source) => {
  expect(violations(source, "/web/src/features/research/panel.ts", "/web/src")).not.toEqual([]);
});

test.each([
  'import { X } from "@/features/catalog";',
  'import { X } from "@/features/catalog/index";',
  'import { X } from "./internal";',
])("public and same-feature imports are allowed: %s", (source) => {
  expect(violations(source, "/web/src/features/research/panel.ts", "/web/src")).toEqual([]);
});
