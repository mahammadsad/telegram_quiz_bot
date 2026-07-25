const { test, expect } = require("@playwright/test");

const {
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

test("personal dashboard shows identity, bookmarks, reports, preferences, and sound control", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  const api = await installApiMocks(page);
  await page.goto("/dashboard.html");

  await expect(page.locator("#identity-card")).toBeVisible();
  await expect(page.locator("#identity-name")).toHaveText("মোবাইল পরীক্ষার্থী");
  await expect(page.locator("#identity-label")).toContainText("আপনার ড্যাশবোর্ড");
  await expect(page.locator("#x-reports")).toHaveText("২");
  await expect(page.locator(".bookmark-item")).toHaveCount(2);

  await page.locator(".bookmark-item").first().getByRole("button", { name: "সরান" }).click();
  await expect(page.locator(".bookmark-item")).toHaveCount(1);
  expect(api.bookmarks).toHaveLength(1);
  expect(api.bookmarks[0].active).toBe(false);

  await page.locator("#settings-card summary").click();
  await expect(page.locator("#revision-sound")).toBeChecked();
  await page.locator("#revision-sound").uncheck();
  await page.locator("#test-sound").click();
  await expect(page.locator("#sound-message")).toContainText("শব্দ বাজানো হয়েছে");
  const audioState = await page.evaluate(() => window.__mobileQa);
  expect(audioState.audioStarts).toBeGreaterThan(0);

  await page.locator("#settings-submit").click();
  await expect(page.locator("#settings-message")).toContainText("সংরক্ষিত হয়েছে");
  expect(api.preferenceSaves).toHaveLength(1);
  expect(api.preferenceSaves[0].revisionSoundEnabled).toBe(false);

  await page.keyboard.press("Tab");
  const focus = await page.evaluate(() => {
    const active = document.activeElement;
    const style = getComputedStyle(active);
    return {
      tag: active.tagName,
      outlineWidth: Number.parseFloat(style.outlineWidth),
      outlineStyle: style.outlineStyle,
    };
  });
  expect(["A", "BUTTON", "INPUT", "SELECT"]).toContain(focus.tag);
  expect(focus.outlineStyle).not.toBe("none");
  expect(focus.outlineWidth).toBeGreaterThanOrEqual(2);

  await capture(page, testInfo, "personal-dashboard");
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("quiz leaderboard highlights a current user who is outside the top ten", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto(`/dashboard.html?quiz=${QUIZ_ID}`);

  await expect(page.locator("#board")).toBeVisible();
  await expect(page.locator("#board .row")).toHaveCount(11);
  await expect(page.locator("#board .separator")).toBeVisible();
  await expect(page.locator("#board .row.me")).toContainText("মোবাইল পরীক্ষার্থী");
  await expect(page.locator("#board .row.me .you")).toHaveText("আপনি");
  await expect(page.locator("#your-rank")).toContainText("আপনার র‍্যাঙ্ক");
  await expect(page.locator("#your-rank")).toContainText("#২৭");

  await capture(page, testInfo, "quiz-leaderboard-outside-top-ten");
  await assertNoHorizontalOverflow(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("dashboard renders explicit empty states without broken controls", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  await installApiMocks(page, {
    emptyDashboard: true,
    emptyBookmarks: true,
    emptyLeaderboard: true,
  });
  await page.goto("/dashboard.html");

  await expect(page.locator("#identity-card")).toBeVisible();
  await expect(page.locator("#bookmarks")).toContainText("এখনও কোনো বুকমার্ক নেই");
  await expect(page.locator("#recent-quizzes")).toContainText("এখনও কোনো সম্পন্ন কুইজ নেই");
  await expect(page.locator("#board-state")).toContainText("এখনও পর্যাপ্ত ফলাফল নেই");
  await capture(page, testInfo, "dashboard-empty-states");
  await assertNoHorizontalOverflow(page);
});
