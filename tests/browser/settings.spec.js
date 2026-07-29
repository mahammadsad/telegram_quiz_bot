const { test, expect } = require("@playwright/test");

const {
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

test("preferences and privacy live in a dedicated settings destination", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  const api = await installApiMocks(page);
  await page.goto("/settings.html");

  await expect(page.getByRole("heading", { name: "পছন্দ ও গোপনীয়তা" })).toBeVisible();
  await expect(page.locator("#settings")).toBeVisible();
  await expect(page.locator("#daily-target")).toHaveValue("30");
  await expect(page.locator("#leaderboard-visible")).toBeChecked();
  await expect(page.locator("#revision-sound")).toBeChecked();
  await expect(page.getByRole("link", { name: "সেটিংস" })).toHaveClass(/active/);
  await expect(page.getByRole("link", { name: "সেটিংস" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await page.locator("#revision-sound").uncheck();
  await page.locator("#test-sound").click();
  await expect(page.locator("#sound-message")).toContainText("শব্দ বাজানো হয়েছে");
  const audioState = await page.evaluate(() => window.__mobileQa);
  expect(audioState.audioStarts).toBeGreaterThan(0);

  await page.locator("#settings-submit").click();
  await expect(page.locator("#settings-message")).toContainText("সংরক্ষিত হয়েছে");
  expect(api.preferenceSaves).toHaveLength(1);
  expect(api.preferenceSaves[0].revisionSoundEnabled).toBe(false);
  expect(api.preferenceSaves[0].leaderboardVisible).toBe(true);

  await capture(page, testInfo, "dedicated-settings");
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("settings gives a safe Telegram-only state without authentication", async ({
  page,
}) => {
  await installApiMocks(page);
  await page.goto("/settings.html");

  await expect(page.locator("#settings")).toBeHidden();
  await expect(page.locator("#settings-state-copy")).toContainText(
    "Telegram-এর কুইজ বাটন",
  );
  await expect(page.locator("#settings-retry")).toBeHidden();
});
