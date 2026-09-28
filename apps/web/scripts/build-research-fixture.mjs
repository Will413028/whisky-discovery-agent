import {mkdirSync, writeFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {build} from "esbuild";

const target = new URL("../.artifacts/research-fixture/", import.meta.url);
mkdirSync(target, {recursive:true});
writeFileSync(new URL("index.html", target), '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>合成研究流程驗收</title><div id="fixture"></div><script type="module" src="/research-client.js"></script></html>');
await build({
  entryPoints:[fileURLToPath(new URL("../tests/research/client.tsx", import.meta.url))],
  outfile:fileURLToPath(new URL("client.js", target)), bundle:true, platform:"browser", format:"esm",
  alias:{
    "@auth0/auth0-react":fileURLToPath(new URL("../tests/research/mock-auth.ts", import.meta.url)),
    "next/navigation":fileURLToPath(new URL("../tests/research/mock-router.ts", import.meta.url)),
  },
});
