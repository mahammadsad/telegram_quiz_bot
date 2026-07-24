const { test, expect } = require("@playwright/test");

const {
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

async function openPractice(page, source, options = {}) {
  await installTelegramMock(page);
  const api = await installApiMocks(page, {
    practiceSource: source,
    ...options,
  });
  await page.goto(`/practice.html?source=${source}`);
  return api;
}

test("revision queue reveals checked answers, reports issues, and plays one mistake sound", async ({
  page,
}, testInfo) => {
  const api = await openPractice(page, "due");
  await expect(page.locator("#practice")).toBeVisible();
  await expect(page.locator(".option")).toHaveCount(4);
  await expect(page.locator("#feedback")).toBeHidden();
  await expect(page.getByText("সঠিক উত্তর:", { exact: false })).toHaveCount(0);

  await page.locator(".option").first().click();
  await page.locator("#marked").check();
  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toBeVisible();
  await expect(page.locator("#feedback")).toContainText("সঠিক উত্তর");
  await expect(page.locator("#feedback")).toContainText("যাচাইকৃত পুনরাবৃত্তি ব্যাখ্যা");
  await expect(page.locator("#feedback a")).toHaveAttribute("rel", "noopener noreferrer");

  expect(api.practiceSubmissions).toHaveLength(1);
  expect(api.practiceSubmissions[0].mode).toBe("revision");
  expect(api.practiceSubmissions[0].sourceType).toBe("due");
  expect(api.practiceSubmissions[0].markedForReview).toBe(true);
  const feedbackState = await page.evaluate(() => window.__mobileQa);
  expect(feedbackState.audioStarts).toBe(1);

  await page.locator("#feedback details summary").click();
  await page.locator("#feedback .report-fields button").click();
  await expect(page.locator("#feedback .report-message")).toContainText("গ্রহণ করা হয়েছে");
  expect(api.reports).toHaveLength(1);
  await capture(page, testInfo, "revision-wrong-answer-report");

  await page.locator("#next").click();
  await page.locator(".option").nth(2).click();
  await page.locator("#submit").click();
  await page.locator("#next").click();
  await expect(page.locator("#empty-message")).toContainText("পরবর্তী সময়সূচি আপডেট");

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("bookmark practice never plays the revision-only mistake sound", async ({
  page,
}) => {
  const api = await openPractice(page, "bookmark");
  await expect(page.locator("#practice")).toBeVisible();
  await expect(page.locator("#title")).toContainText("বুকমার্ক অনুশীলন");

  await page.locator(".option").first().click();
  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toBeVisible();
  expect(api.practiceSubmissions).toHaveLength(1);
  expect(api.practiceSubmissions[0].mode).toBe("practice");
  expect(api.practiceSubmissions[0].sourceType).toBe("bookmark");
  await expect(page.locator("#feedback details")).toHaveCount(0);

  const feedbackState = await page.evaluate(() => window.__mobileQa);
  expect(feedbackState.audioContexts).toBe(0);
  expect(feedbackState.audioStarts).toBe(0);
});

test("practice network retry preserves the same client attempt ID", async ({
  page,
}, testInfo) => {
  const api = await openPractice(page, "due", { failFirstPractice: true });
  await page.locator(".option").nth(1).click();
  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toContainText("নিশ্চিত হয়নি");
  expect(api.practiceSubmissions).toHaveLength(1);
  const attemptId = api.practiceSubmissions[0].attemptId;

  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toContainText("উত্তরটি ভুল");
  expect(api.practiceSubmissions).toHaveLength(2);
  expect(api.practiceSubmissions[1].attemptId).toBe(attemptId);
  await capture(page, testInfo, "practice-idempotent-retry");
});

test("practice queue has a clear empty state", async ({ page }, testInfo) => {
  await openPractice(page, "due", { emptyPractice: true });
  await expect(page.locator("#empty")).toBeVisible();
  await expect(page.locator("#empty-message")).toContainText("কোনো প্রশ্ন নেই");
  await capture(page, testInfo, "practice-empty-state");
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
});
