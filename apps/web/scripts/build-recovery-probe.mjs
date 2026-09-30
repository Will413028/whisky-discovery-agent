// Explicit live T09 diagnostics, mounted temporarily outside normal app images.
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const target = new URL("../.artifacts/recovery-probe/", import.meta.url);
mkdirSync(target, { recursive: true });
const define = { "process.env.NODE_ENV": JSON.stringify("production") };
for (const key of ["NEXT_PUBLIC_AUTH0_DOMAIN", "NEXT_PUBLIC_AUTH0_CLIENT_ID", "NEXT_PUBLIC_AUTH0_AUDIENCE"]) {
  if (!process.env[key]) throw new Error(`Missing public config: ${key}`);
  define[`process.env.${key}`] = JSON.stringify(process.env[key]);
}
await build({ entryPoints: [fileURLToPath(new URL("../tests/stream/recovery-probe.tsx", import.meta.url))],
  outfile: fileURLToPath(new URL("__recovery_probe.js", target)), bundle: true, platform: "browser", format: "esm",
  jsx: "automatic", define, minify: true });
writeFileSync(new URL("__recovery_probe.html", target), '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T09 API 驗收</title><div id="probe"></div><script type="module" src="/__recovery_probe.js"></script></html>');
