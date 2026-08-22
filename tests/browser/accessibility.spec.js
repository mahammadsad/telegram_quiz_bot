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
