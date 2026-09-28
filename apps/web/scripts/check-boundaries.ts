import { parse } from "@babel/parser";
import { dirname, relative, resolve } from "node:path";

export function violations(source: string, file: string, root: string): string[] {
  const errors: string[] = [];
  const origin = relative(root, file).split("/");
  const tree = parse(source, { sourceType: "module", plugins: ["typescript", "jsx"], createImportExpressions: true });
  function check(specifier: string) {
    const target = specifier.startsWith("@/") ? resolve(root, specifier.slice(2))
      : specifier.startsWith(".") ? resolve(dirname(file), specifier) : undefined;
    if (!target) return;
    const imported = relative(root, target).split("/");
    if (origin[0] === "shared" && imported[0] === "features") {
      errors.push(`${file}: shared imports feature ${specifier}`);
    }
    if (origin[0] === "features" && imported[0] === "features" && origin[1] !== imported[1]
      && imported.length > 2 && !(imported.length === 3 && /^index(?:\.[jt]sx?)?$/.test(imported[2]))) {
      errors.push(`${file}: cross-feature internal ${specifier}`);
    }
  }
  function walk(value: unknown): void {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) { value.forEach(walk); return; }
    const node = value as Record<string, unknown>;
    if (["ImportDeclaration", "ExportNamedDeclaration", "ExportAllDeclaration", "ImportExpression"].includes(String(node.type))) {
      const specifier = node.source as { value?: string } | undefined;
      if (typeof specifier?.value === "string") check(specifier.value);
    }
    Object.values(node).forEach(walk);
  }
  walk(tree);
  return errors;
}
