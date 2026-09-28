import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const target = new URL("../.artifacts/stream-fixture/", import.meta.url);
mkdirSync(target, {recursive:true});
writeFileSync(new URL("index.html", target), '<!doctype html><meta charset="utf-8"><title>合成串流測試</title><h1>合成串流測試，非產品資料</h1><output></output><script type="module" src="/client.js"></script>');
await build({entryPoints:[fileURLToPath(new URL("../tests/stream/client.ts", import.meta.url))], outfile:fileURLToPath(new URL("client.js", target)), bundle:true, platform:"browser", format:"esm"});
