const { test, expect } = require("@playwright/test");
const { QUIZ_ID, installApiMocks, installTelegramMock } = require("./fixtures");

// Deterministic text-only stress test, not a claim of native OS text scaling
// or real browser-chrome zoom coverage. Snapshot before applying sizes to avoid
// compounding inherited fonts; leave the viewport and non-text geometry alone.
async function doubleTextSize(page) {
  await page.evaluate(() => {
    const sizes = Array.from(document.querySelectorAll("body *"), (element) => [
      element, Number.parseFloat(getComputedStyle(element).fontSize),
    ]);
    sizes.forEach(([element, size]) => {
      element.style.setProperty("font-size", `${size * 2}px`, "important");
    });
  });
}

async function expectContainedText(locator) {
  const overflow = await locator.evaluate((container) => {
    const bounds = container.getBoundingClientRect();
    return [container, ...container.querySelectorAll("*")].filter((element) => {
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height || element instanceof SVGElement) return false;
      return element.scrollWidth > element.clientWidth + 2 ||
        rect.left < bounds.left - 2 || rect.right > bounds.right + 2;
    }).map((element) => element.id || element.className || element.tagName);
  });
  expect(overflow).toEqual([]);
}

test("daily quiz summary and review controls reflow with doubled text", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);
  await page.locator("#btn-start").click();
  await expect(page.locator("#screen-quiz")).toBeVisible();
  await doubleTextSize(page);
  await expectContainedText(page.locator("#question-map-toggle"));
  await expectContainedText(page.locator(".question-tools"));
  await page.locator("#btn-mark").click();
  await expect(page.locator("#btn-mark")).toHaveAttribute("aria-pressed", "true");
  await page.locator("#question-map-toggle").click();
  await expect(page.locator("#question-map-sheet")).toBeVisible();
});

test("settings save stays above enlarged navigation and the safe area", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page);
  await page.goto("/settings.html");
  await expect(page.locator("#settings")).toBeVisible();
  await page.evaluate(() => document.documentElement.style.setProperty(
    "--tg-content-safe-area-inset-bottom", "34px",
  ));
  await doubleTextSize(page);
  // Scroll into the form so the sticky footer is not constrained by its
  // containing block's top edge beneath the unusually tall enlarged header.
  await page.locator("#daily-target").scrollIntoViewIfNeeded();
  await expect.poll(async () => page.evaluate(() => {
    const save = document.querySelector(".save-card").getBoundingClientRect();
    const nav = document.querySelector("nav.bottom").getBoundingClientRect();
    return nav.top - save.bottom;
  })).toBeGreaterThanOrEqual(8);
});

for (const path of ["/", "/settings.html", "/dashboard.html", "/mock.html", "/syllabus.html"]) {
  test(`${path} navigation fits with doubled text`, async ({ page }) => {
    await installTelegramMock(page, { nativeActions: false, startParam: "" });
    await installApiMocks(page);
    await page.goto(path);
    const nav = page.locator("nav.bottom, nav.bottom-nav");
    await expect(nav).toBeVisible();
    await doubleTextSize(page);
    await expectContainedText(nav);
    await expect(nav.locator("a")).toHaveCount(4);
  });
}
