const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const {
  QUIZ_ID,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

async function expectWcag22Aa(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test("Bengali preparation hub satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page, { startParam: "" });
  await installApiMocks(page);
  await page.goto("/");

  await expect(page.locator("#screen-home")).toBeVisible();
  await expectWcag22Aa(page);
});

test("quiz start experience satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);

  await expect(page.locator("#screen-intro")).toBeVisible();
  await expectWcag22Aa(page);
});

test("dashboard satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/dashboard.html");

  await expect(page.locator("#content")).toBeVisible();
  await expectWcag22Aa(page);
});

test("settings satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/settings.html");

  await expect(page.locator("#settings")).toBeVisible();
  await expectWcag22Aa(page);
});

test("revision practice satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#practice")).toBeVisible();
  await expectWcag22Aa(page);
});
