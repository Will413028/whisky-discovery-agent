import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: { baseURL: "http://127.0.0.1:3418", trace: "retain-on-failure" },
  webServer: [{
    command: "pnpm preview",
    url: "http://127.0.0.1:3418",
    reuseExistingServer: false,
    timeout: 60_000,
  }, {
    command: "uv run --project ../../backend python ../../backend/tests/fixtures/stream_server.py --port 8419",
    url: "http://127.0.0.1:8419/health", reuseExistingServer:false, timeout:60_000,
  }, {
    command: "node scripts/build-stream-fixture.mjs && wrangler dev --config tests/stream/wrangler.jsonc --port 3420 --ip 127.0.0.1",
    url: "http://127.0.0.1:3420", reuseExistingServer:false, timeout:60_000,
  }],
});
