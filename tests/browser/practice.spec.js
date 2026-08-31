const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const {
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

async function expectWcag22Aa(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

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
  await expect(page.locator("#source-due")).toHaveClass(/active/);
  await expect(page.locator("#source-due")).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".option")).toHaveCount(4);
  await expect(page.locator("#feedback")).toBeHidden();
  await expect(page.getByText("সঠিক উত্তর:", { exact: false })).toHaveCount(0);
  await expect(page.locator("#submit")).toBeDisabled();

  await page.locator(".option").first().click();
  await expect(page.locator("#submit")).toBeEnabled();
  await page.locator("#marked").check();
  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toBeVisible();
  await expect(page.locator("#feedback")).toContainText("সঠিক উত্তর");
  await expect(page.locator("#feedback")).toContainText("যাচাইকৃত পুনরাবৃত্তি ব্যাখ্যা");
  await expect(page.locator("#feedback a")).toHaveAttribute("rel", "noopener noreferrer");
  await expectWcag22Aa(page);

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
  await expect(page.locator("#completed")).toBeVisible();
  await expect(page.locator("#empty")).toBeHidden();
  await expect(page.locator("#completed-message")).toContainText("সময়সূচি আপডেট");
  await expect(page.locator("#completed-count")).toHaveText("২");

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("bookmark practice never plays the revision-only mistake sound", async ({
  page,
}) => {
  const api = await openPractice(page, "bookmark");
  await expect(page.locator("#practice")).toBeVisible();
  await expect(page.locator("#source-bookmark")).toHaveClass(/active/);
  await expect(page.locator("#source-bookmark")).toHaveAttribute("aria-current", "page");
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
  await expect(page.locator("#completed")).toBeHidden();
  await expect(page.locator("#count")).toHaveText("০");
  await expect(page.locator("#empty-title")).toContainText("পুনরাবৃত্তি শেষ");
  await expect(page.locator("#empty-message")).toContainText("কোনো প্রশ্ন বাকি নেই");
  await capture(page, testInfo, "practice-empty-state");
  await page.locator("#empty-quiz-link").click();
  await expect(page.locator("#screen-intro")).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
});

test("practice loads its queue and presentation preferences from one bootstrap", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  const learnerReads = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/me/")) learnerReads.push(url.pathname);
  });

  await page.goto("/practice.html?source=due");
  await expect(page.locator("#practice")).toBeVisible({ timeout: 1000 });
  await expect(page.locator("#count")).toHaveText("২টি");
  expect(learnerReads.filter((path) => path === "/api/me/practice-bootstrap")).toHaveLength(1);
  expect(learnerReads).not.toContain("/api/me/preferences");
});

test("practice load failure keeps the count unknown and shows an auth recovery", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  await page.route(/\/api\/me\/practice-bootstrap(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      headers: { "X-Request-ID": "practice-auth-401" },
      body: JSON.stringify({ detail: "raw backend detail must not be shown" }),
    }),
  );

  await page.goto("/practice.html?source=due");
  await expect(page.locator("#error")).toBeVisible();
  await expect(page.locator("#error")).toHaveAttribute("data-state", "auth_expired");
  await expect(page.locator("#error-title")).toContainText("সেশনের মেয়াদ শেষ");
  await expect(page.locator("#count")).toHaveText("—");
  await expect(page.locator("#empty")).toBeHidden();
  await expect(page.locator("#retry")).toBeHidden();
  await expect(page.locator("#auth-reopen")).toBeVisible();
  await expect(page.getByText("raw backend detail must not be shown")).toHaveCount(0);
});

test("practice distinguishes rate limits and temporary server failures", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  let status = 429;
  let requests = 0;
  await page.route(/\/api\/me\/practice-bootstrap(?:\?.*)?$/, (route) => {
    requests += 1;
    return route.fulfill({
      status,
      contentType: "application/json",
      headers: { "Retry-After": "1", "X-Request-ID": `practice-${status}` },
      body: JSON.stringify({ detail: "private diagnostic" }),
    });
  });

  await page.goto("/practice.html?source=due");
  await expect(page.locator("#error")).toHaveAttribute("data-state", "rate_limited");
  await expect(page.locator("#error-title")).toContainText("বিরতি");
  await expect(page.locator("#retry")).toBeDisabled();
  await expect(page.locator("#retry")).toBeEnabled({ timeout: 2500 });
  expect(requests).toBe(1);

  status = 503;
  await page.locator("#retry").click();
  await expect(page.locator("#error")).toHaveAttribute("data-state", "server_temporary");
  await expect(page.locator("#error-title")).toContainText("সাময়িকভাবে ব্যস্ত");
  await expect(page.locator("#count")).toHaveText("—");
  expect(requests).toBe(3);
});
