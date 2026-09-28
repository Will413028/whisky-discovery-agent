import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: { baseURL: "http://127.0.0.1:3418", trace: "retain-on-failure" },
  webServer: {
    command: "pnpm preview",
    url: "http://127.0.0.1:3418",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
