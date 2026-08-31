const { defineConfig } = require("@playwright/test");

const launchOptions = {
  // Chromium fetches a service-worker script outside the page request path, so
  // Playwright's ignoreHTTPSErrors context option alone is not sufficient for
  // this deliberately self-signed, loopback-only test server.
  args: [
    "--ignore-certificate-errors",
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? ["--no-sandbox"] : []),
  ],
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
    : {}),
};

module.exports = defineConfig({
  testDir: "./tests/browser-service-worker",
  outputDir: "test-results/service-worker-https",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 7_500,
  },
  reporter: [["line"]],
  use: {
    baseURL: "https://127.0.0.1:4443",
    ignoreHTTPSErrors: true,
    locale: "bn-IN",
    timezoneId: "Asia/Kolkata",
    serviceWorkers: "allow",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    launchOptions,
  },
  projects: [
    {
      name: "chromium-service-worker-https",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: {
    command: "node tests/browser-service-worker/https-server.js",
    url: "https://127.0.0.1:4443/tests/browser-service-worker/harness.html",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
