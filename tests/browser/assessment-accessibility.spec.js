const { test, expect } = require("@playwright/test");
const {
  QUIZ_ID,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

test("keyboard selection does not submit the previously selected practice answer", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  const api = await installApiMocks(page, { practiceSource: "due" });
  await page.goto("/practice.html?source=due");
  await expect(page.locator("#practice")).toBeVisible();
  await page.locator(".option").first().click();
  await page.locator(".option").nth(1).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".option").nth(1)).toHaveAttribute("aria-pressed", "true");
  expect(api.practiceSubmissions).toHaveLength(0);
  await page.locator("#submit").focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => api.practiceSubmissions.length).toBe(1);
  expect(api.practiceSubmissions[0].selectedIndex).toBe(1);
});

test("practice shortcuts ignore loading screens and modified key presses", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, { practiceSource: "due" });
  let releaseQueue;
  const queueGate = new Promise((resolve) => { releaseQueue = resolve; });
  await page.route("**/api/me/practice-bootstrap**", async (route) => {
    await queueGate;
    await route.fallback();
  });
  await page.goto("/practice.html?source=due");
  await page.keyboard.press("1");
  releaseQueue();
  await expect(page.locator("#practice")).toBeVisible();
  expect(errors).toEqual([]);
  await expect(page.locator(".option[aria-pressed=true]")).toHaveCount(0);
  await page.locator("#question").focus();
  await page.keyboard.press("Control+2");
  await expect(page.locator(".option[aria-pressed=true]")).toHaveCount(0);
  await page.keyboard.press("2");
  await expect(page.locator(".option").nth(1)).toHaveAttribute("aria-pressed", "true");
});

for (const screen of ["quiz", "practice"]) {
  test(`${screen} selection stays distinguishable when forced colors remove backgrounds`, async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await installTelegramMock(page, { nativeActions: false });
    await installApiMocks(page, { practiceSource: "due" });
    if (screen === "quiz") {
      await page.goto(`/index.html?quiz=${QUIZ_ID}`);
      await expect(page.locator("#screen-intro")).toBeVisible();
      await page.locator("#btn-start").click();
      await expect(page.locator("#screen-quiz")).toBeVisible();
    } else {
      await page.goto("/practice.html?source=due");
      await expect(page.locator("#practice")).toBeVisible();
    }
    await page.locator(".option").first().click();
    await page.keyboard.press("Control+2");
    await expect(page.locator(".option").first()).toHaveAttribute("aria-pressed", "true");
    const borders = await page.locator(".option").evaluateAll((options) => options.slice(0, 2).map((option) => {
      const style = getComputedStyle(option);
      return { width: style.borderTopWidth, style: style.borderTopStyle };
    }));
    expect(borders[0]).not.toEqual(borders[1]);
  });
}

test("Telegram Back cancels a settings selector draft and restores its trigger", async ({ page }) => {
  await installTelegramMock(page);
  const api = await installApiMocks(page);
  await page.goto("/settings.html");
  await expect(page.locator("#settings")).toBeVisible();
  await page.locator("#open-subject-dialog").click();
  await page.getByLabel("ইতিহাস", { exact: true }).uncheck();
  expect(await page.evaluate(() => window.__mobileQa.backVisible)).toBe(true);
  await page.evaluate(() => window.__triggerBackButton());
  await expect(page.locator("#subject-dialog")).toBeHidden();
  await expect(page.locator("#open-subject-dialog")).toBeFocused();
  await expect(page.locator("#subject-summary")).toContainText("২টি");
  await expect(page.locator("#settings-submit")).toBeDisabled();
  expect(api.preferenceSaves).toHaveLength(0);
  expect(await page.evaluate(() => window.__mobileQa.backVisible)).toBe(false);
});
