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
  await expect(page.locator("#display-name")).toHaveValue("");
  await expect(page.locator("#privacy-guidance")).toContainText(
    "Telegram নাম কখনও নিজে থেকে প্রকাশ করা হবে না",
  );
  await expect(page.locator("#privacy-guidance")).toContainText(
    "গোপন শিক্ষার্থী নাম",
  );
  await expect(page.locator("#revision-sound")).toBeChecked();
  await expect(page.locator("#settings-submit")).toBeDisabled();
  await expect(page.locator("#subject-summary")).toContainText("২টি নির্বাচিত");
  await expect(page.locator("#exam-summary")).toContainText("২টি নির্বাচিত");
  await expect(page.locator("#reminder")).toBeDisabled();
  await expect(page.getByText("দৈনিক স্মরণবার্তা — শীঘ্রই আসছে")).toBeVisible();
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
  expect(api.preferenceSaves[0].dailyReminderEnabled).toBe(false);

  await capture(page, testInfo, "dedicated-settings");
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("subject-first selectors keep a draft until Done and save only dirty changes", async ({
  page,
}) => {
  await installTelegramMock(page);
  const api = await installApiMocks(page);
  await page.goto("/settings.html");
  await expect(page.locator("#settings")).toBeVisible();
  await expect(page.locator("#settings-submit")).toBeDisabled();

  await page.locator("#open-subject-dialog").click();
  await expect(page.locator("#subject-dialog")).toBeVisible();
  await page.getByLabel("ইতিহাস", { exact: true }).uncheck();
  await expect(page.locator("#subject-dialog-count")).toContainText("১টি");
  await page.locator("#subject-dialog-close").click();
  await expect(page.locator("#subject-dialog")).toBeHidden();
  await expect(page.locator("#subject-summary")).toContainText("২টি");
  await expect(page.locator("#settings-submit")).toBeDisabled();

  await page.locator("#open-subject-dialog").click();
  await expect(page.getByLabel("ইতিহাস", { exact: true })).toBeChecked();
  await page.getByLabel("ইতিহাস", { exact: true }).uncheck();
  await page.getByLabel("বিজ্ঞান", { exact: true }).check();
  await page.locator("#subject-done").click();
  await expect(page.locator("#subject-summary")).toContainText("২টি");
  await expect(page.locator("#settings-submit")).toBeEnabled();

  await page.locator("#settings-submit").click();
  await expect(page.locator("#settings-message")).toContainText("সংরক্ষিত হয়েছে");
  expect(api.preferenceSaves).toHaveLength(1);
  expect(api.preferenceSaves[0].preferredSubjects).toEqual(["geography", "science"]);
  await expect(page.locator("#settings-submit")).toBeDisabled();
});

test("account deletion requires an explicit second step", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  let deletionRequests = 0;
  await page.route("**/api/me/account-deletion", async (route) => {
    deletionRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ gracePeriodDays: 7 }),
    });
  });
  await page.goto("/settings.html");

  await page.locator(".danger-zone").getByText("অ্যাকাউন্ট ও ডেটা").click();
  await page.locator("#request-deletion").click();
  await expect(page.locator("#deletion-confirm")).toBeVisible();
  expect(deletionRequests).toBe(0);
  await page.locator("#confirm-deletion").click();
  await expect(page.locator("#privacy-message")).toContainText("৭ দিনের মধ্যে");
  expect(deletionRequests).toBe(1);
});

test("clearing public identity consent immediately restores an anonymous rank", async ({
  page,
}) => {
  await installTelegramMock(page);
  const api = await installApiMocks(page);
  await page.goto("/settings.html");

  await page.locator("#display-name").fill("আমার প্রকাশ্য নাম");
  await page.locator("#username-visible").check();
  await page.locator("#settings-submit").click();
  await expect(page.locator("#settings-message")).toContainText("সংরক্ষিত হয়েছে");
  expect(api.preferenceSaves[0].publicDisplayName).toBe("আমার প্রকাশ্য নাম");
  expect(api.preferenceSaves[0].usernameVisible).toBe(true);

  await page.locator("#display-name").fill("");
  await page.locator("#username-visible").uncheck();
  await page.locator("#settings-submit").click();
  await expect.poll(() => api.preferenceSaves.length).toBe(2);
  expect(api.preferenceSaves[1].publicDisplayName).toBeNull();
  expect(api.preferenceSaves[1].usernameVisible).toBe(false);

  await page.goto("/dashboard.html");
  await expect(page.locator("#identity-name")).toHaveText("মোবাইল পরীক্ষার্থী");
  await expect(page.locator("#board .row.me")).toContainText(
    "শিক্ষার্থী ABCDEF012345",
  );
  await expect(page.locator("#board .row.me")).not.toContainText(
    "মোবাইল পরীক্ষার্থী",
  );
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
