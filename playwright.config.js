const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  testMatch: "*.spec.js",
  fullyParallel: false,
  reporter: "list",
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || "./test-results",
  use: {
    baseURL: "http://127.0.0.1:8766",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python tests/e2e/server.py",
    url: "http://127.0.0.1:8766/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
