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

test("personal dashboard keeps bookmark questions in Practice and omits a bookmark list", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/dashboard.html");

  await expect(page.locator("#identity-card")).toBeVisible();
  await expect(page.locator("#identity-name")).toHaveText("মোবাইল পরীক্ষার্থী");
  await expect(page.locator("#identity-avatar img")).toHaveAttribute(
    "src",
    "https://example.invalid/private-dashboard.jpg",
  );
  await expect(page.locator("#identity-label")).toContainText("আপনার ড্যাশবোর্ড");
  await expect(page.locator("#x-reports")).toHaveText("২");
  await expect(page.locator("#x-bookmarks")).toHaveText("১");
  await expect(page.locator("#bookmarks-card")).toHaveCount(0);
  await expect(page.locator(".bookmark-item")).toHaveCount(0);
  await expect(page.locator("#bookmark-practice")).toBeVisible();
  await expect(page.locator("#bookmark-practice")).toHaveAttribute(
    "href",
    "practice.html?source=bookmark",
  );
  await expect(page.locator("#mastery-card a[href*='source=bookmark']")).toHaveCount(0);
  await expect(page.locator("#due-revision")).toHaveAttribute(
    "href",
    "practice.html?source=due",
  );

  await expect(page.locator("#settings-card")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "সেটিংস" })).toHaveAttribute(
    "href",
    "settings.html",
  );

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
  await expect(page.locator("#board .row.me")).toContainText(
    "শিক্ষার্থী ABCDEF012345",
  );
  await expect(page.locator("#board")).toContainText("স্বেচ্ছায় দেওয়া নাম");
  await expect(page.locator("#board")).toContainText("@public_user");
  await expect(page.locator("#board")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator("#board img")).toHaveCount(0);
  await expect(page.locator("#board .row.me .you")).toHaveText("আপনি");
  await expect(page.locator("#your-rank")).toContainText("আপনার র‍্যাঙ্ক");
  await expect(page.locator("#your-rank")).toContainText("#২৭");
  await expect(page.locator("#your-rank")).toContainText("৬.২৫/১০");
  await expect(page.locator("#rank-help")).toContainText("০.২৫ নম্বর কাটা হয়");

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
    emptyLeaderboard: true,
  });
  await page.goto("/dashboard.html");

  await expect(page.locator("#identity-card")).toBeVisible();
  await expect(page.locator("#bookmarks-card")).toHaveCount(0);
  await expect(page.locator("#bookmark-practice")).toBeVisible();
  await expect(page.locator("#recent-quizzes")).toContainText("এখনও কোনো সম্পন্ন কুইজ নেই");
  await expect(page.locator("#board-state")).toContainText("এখনও পর্যাপ্ত ফলাফল নেই");
  await capture(page, testInfo, "dashboard-empty-states");
  await assertNoHorizontalOverflow(page);
});

test("personal dashboard quiz link returns to the live quiz instead of a raw 404", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/dashboard.html");
  await expect(page.locator("#identity-card")).toBeVisible();

  await page.locator("#page-link").click();
  await expect
    .poll(() => page.evaluate(() => location.pathname + location.search))
    .toBe(`/?quiz=${QUIZ_ID}`);
  await expect(page.locator("#screen-intro")).toBeVisible();
  await expect(page.locator("#quiz-id-pill")).toContainText(QUIZ_ID);
});
