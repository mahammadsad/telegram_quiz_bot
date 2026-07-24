const { defineConfig } = require("@playwright/test");

const viewports = [
  ["android-320x568", { width: 320, height: 568 }],
  ["android-360x800", { width: 360, height: 800 }],
  ["android-390x844", { width: 390, height: 844 }],
  ["android-412x915", { width: 412, height: 915 }],
];

module.exports = defineConfig({
  testDir: "./tests/browser",
  outputDir: "test-results",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 1,
  timeout: 45_000,
  expect: {
    timeout: 7_500,
  },
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:4173",
    locale: "bn-IN",
    timezoneId: "Asia/Kolkata",
    colorScheme: "light",
    reducedMotion: "no-preference",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? "off"
      : "retain-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
          args: ["--no-sandbox"],
        }
      : {},
  },
  projects: viewports.map(([name, viewport]) => ({
    name,
    use: { viewport },
  })),
  webServer: {
    command: "python3 -m http.server 4173 --bind 127.0.0.1",
    url: "http://127.0.0.1:4173/index.html",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
