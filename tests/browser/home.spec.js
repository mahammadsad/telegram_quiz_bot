const { test, expect } = require("@playwright/test");

const {
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

test("root Mini App opens a useful preparation home without a quiz deep link", async ({ page }) => {
  await installTelegramMock(page, { startParam: "" });
  await installApiMocks(page);
  await page.goto("/");

  await expect(page.locator("#screen-home")).toBeVisible();
  await expect(page.getByRole("heading", { name: "আজ কী পড়বেন?" })).toBeVisible();
  await expect(page.locator("#quiz-catalogue .quiz-card")).toHaveCount(2);
  await expect(page.locator("#quiz-catalogue")).toContainText("আধুনিক ভারত");
  await expect(page.getByRole("link", { name: /পূর্ণাঙ্গ মক টেস্ট/ })).toHaveAttribute(
    "href",
    "mock.html",
  );

  await page.locator(`a[href*="${QUIZ_ID}"]`).click();
  await expect(page.locator("#screen-intro")).toBeVisible();
  await expect(page.locator("#quiz-id-pill")).toContainText(QUIZ_ID);

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("home keeps core study paths available when recent quizzes cannot load", async ({ page }) => {
  await installTelegramMock(page, { startParam: "" });
  await installApiMocks(page, { failRecentQuizzes: true });
  await page.goto("/");

  await expect(page.locator("#screen-home")).toBeVisible();
  await expect(page.locator("#quiz-catalogue")).toContainText("লোড করা যাচ্ছে না");
  await expect(page.locator("#btn-home-retry")).toBeVisible();
  await expect(page.getByRole("link", { name: /আজকের পুনরাবৃত্তি/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /আমার অগ্রগতি/ })).toBeVisible();
});

test("preference assignment opens only the requested recent subject", async ({ page }) => {
  await installTelegramMock(page, { startParam: "" });
  await installApiMocks(page);
  await page.goto("/?subject=geography");

  await expect(page.locator("#screen-home")).toBeVisible();
  await expect(page.locator("#quiz-catalogue .quiz-card")).toHaveCount(1);
  await expect(page.locator("#quiz-catalogue")).toContainText("ভূগোল");
  await expect(page.locator("#quiz-catalogue")).not.toContainText("ইতিহাস");
});
