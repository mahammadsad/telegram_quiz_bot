const { test, expect } = require("@playwright/test");

const {
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  installApiMocks,
  installTelegramMock,
  quizPayload,
} = require("./fixtures");

async function openIntro(page, options = {}) {
  await installTelegramMock(page);
  const api = await installApiMocks(page, options);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);
  await expect(page.locator("#screen-intro")).toBeVisible();
  return api;
}

async function startWithTelegramMainButton(page) {
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#screen-quiz")).toBeVisible();
}

async function openSubmissionConfirmation(page) {
  await page.locator(".nav-q").nth(9).click();
  await page.locator(".option").first().click();
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#submit-modal")).toBeVisible();
}

test("complete quiz lifecycle hides answers until submission and recovers the result", async ({
  page,
}, testInfo) => {
  const api = await openIntro(page, { quizSubmitDelayMs: 250 });

  expect(JSON.stringify(quizPayload())).not.toContain("correctIndex");
  expect(JSON.stringify(quizPayload())).not.toContain("explanation");
  await expect(page.locator("#review-list")).toBeEmpty();
  await expect(page.locator("#screen-result")).toBeHidden();
  await capture(page, testInfo, "quiz-intro");

  await startWithTelegramMainButton(page);
  await expect(page.locator(".option")).toHaveCount(4);
  await expect(page.locator("#q-text")).toContainText("বাংলার নবজাগরণ");

  const wrapping = await page.locator("#q-text").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      height: element.getBoundingClientRect().height,
      lineHeight: Number.parseFloat(style.lineHeight),
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    };
  });
  expect(wrapping.height).toBeGreaterThan(wrapping.lineHeight * 1.5);
  expect(wrapping.scrollWidth).toBeLessThanOrEqual(wrapping.clientWidth + 1);

  await page.locator(".option").nth(1).click();
  await page.locator("#btn-mark").click();
  await expect(page.locator("#btn-mark")).toHaveAttribute("aria-pressed", "true");
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#q-index")).toContainText("২");
  await page.evaluate(() => window.__triggerBackButton());
  await expect(page.locator("#q-index")).toContainText("১");
  await page.locator(".nav-q").nth(4).click();
  await expect(page.locator("#q-index")).toContainText("৫");
  await page.keyboard.press("3");
  await expect(page.locator(".option").nth(2)).toHaveClass(/selected/);

  const draftBeforeRefresh = await page.evaluate(() =>
    JSON.parse(localStorage.getItem(`telegram-quiz-draft:${new URLSearchParams(location.search).get("quiz")}`)),
  );
  expect(draftBeforeRefresh.answers[0]).toBe(1);
  expect(draftBeforeRefresh.markedForReview[0]).toBe(true);
  expect(draftBeforeRefresh.answers[4]).toBe(2);

  await capture(page, testInfo, "quiz-answered-marked");
  await page.reload();
  await expect(page.locator("#resume-box")).toBeVisible();
  await page.locator("#btn-resume").click();
  await expect(page.locator("#q-index")).toContainText("৫");

  await openSubmissionConfirmation(page);
  await page.locator("#btn-submit-confirm").evaluate((button) => {
    button.click();
    button.click();
  });
  await expect(page.locator("#loading-message")).toHaveText("উত্তর সাবমিট হচ্ছে...");
  await expect.poll(() => api.quizSubmissions.length).toBe(1);
  await capture(page, testInfo, "quiz-submission-loading");
  await expect(page.locator("#screen-result")).toBeVisible();

  expect(api.quizSubmissions).toHaveLength(1);
  const firstAttemptId = api.quizSubmissions[0].attemptId;
  expect(firstAttemptId).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  );
  await expect(page.locator(".review")).toHaveCount(10);
  await expect(page.locator(".review .correct").first()).toContainText("সঠিক উত্তর");
  await expect(page.locator(".review .explanation").first()).toContainText(
    "সাবমিটের পর দৃশ্যমান",
  );
  await capture(page, testInfo, "quiz-result-review");

  const firstReview = page.locator(".review").first();
  await firstReview.locator(".bookmark-submit").click();
  await expect(firstReview.locator(".bookmark-submit")).toContainText("বুকমার্ক");
  await firstReview.locator("details").click();
  await firstReview.locator(".report-submit").click();
  await expect(firstReview.locator(".report-message")).toContainText("গ্রহণ করা হয়েছে");
  expect(api.bookmarks).toHaveLength(1);
  expect(api.reports).toHaveLength(1);

  const submissionCount = api.quizSubmissions.length;
  await page.reload();
  await expect(page.locator("#screen-result")).toBeVisible();
  await expect(page.locator("#score-text")).toContainText("৭/১০");
  expect(api.quizSubmissions).toHaveLength(submissionCount);

  await page.locator("#btn-retake").click();
  await expect(page.locator("#screen-quiz")).toBeVisible();
  const retakeAttemptId = await page.evaluate(
    () => JSON.parse(localStorage.getItem(`telegram-quiz-draft:${new URLSearchParams(location.search).get("quiz")}`)).attemptId,
  );
  expect(retakeAttemptId).not.toBe(firstAttemptId);

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("network retry reuses the same attempt ID and reaches one idempotent result", async ({
  page,
}, testInfo) => {
  const api = await openIntro(page, { failFirstQuizSubmission: true });
  await startWithTelegramMainButton(page);
  await openSubmissionConfirmation(page);
  await page.locator("#btn-submit-confirm").click();

  await expect(page.locator("#screen-error")).toBeVisible();
  await expect(page.locator("#error-message")).toContainText("জমা করা যায়নি");
  expect(api.quizSubmissions).toHaveLength(1);
  const attemptId = api.quizSubmissions[0].attemptId;

  await page.locator("#btn-retry").click();
  await expect(page.locator("#submit-modal")).toBeVisible();
  await page.locator("#btn-submit-confirm").click();
  await expect(page.locator("#screen-result")).toBeVisible();

  expect(api.quizSubmissions).toHaveLength(2);
  expect(new Set(api.quizSubmissions.map((item) => item.attemptId))).toEqual(
    new Set([attemptId]),
  );
  await capture(page, testInfo, "quiz-network-retry-result");
});

test("refresh during submission resumes the draft and retries the identical attempt", async ({
  page,
}) => {
  const api = await openIntro(page, { quizSubmitDelayMs: 600 });
  await startWithTelegramMainButton(page);
  await openSubmissionConfirmation(page);
  await page.locator("#btn-submit-confirm").click();
  await expect.poll(() => api.quizSubmissions.length).toBe(1);
  const attemptId = api.quizSubmissions[0].attemptId;

  await page.reload();
  await expect(page.locator("#resume-box")).toBeVisible();
  await page.locator("#btn-resume").click();
  await openSubmissionConfirmation(page);
  await page.locator("#btn-submit-confirm").click();
  await expect(page.locator("#screen-result")).toBeVisible();

  expect(api.quizSubmissions.length).toBeGreaterThanOrEqual(2);
  expect(api.quizSubmissions.every((item) => item.attemptId === attemptId)).toBe(true);
});

test("Telegram MainButton and BackButton follow the current quiz screen", async ({
  page,
}) => {
  await openIntro(page);
  let state = await page.evaluate(() => window.__mobileQa);
  expect(state.ready).toBe(1);
  expect(state.expand).toBe(1);
  expect(state.closingConfirmation).toBe(1);
  expect(state.mainParams.text).toContain("মক টেস্ট শুরু");
  expect(state.mainVisible).toBe(true);
  expect(state.backVisible).toBe(false);

  await startWithTelegramMainButton(page);
  state = await page.evaluate(() => window.__mobileQa);
  expect(state.mainParams.text).toBe("পরবর্তী");
  expect(state.backVisible).toBe(false);

  await page.locator(".option").first().click();
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#q-index")).toContainText("২");
  state = await page.evaluate(() => window.__mobileQa);
  expect(state.backVisible).toBe(true);
  expect(state.haptics).toContain("selection");

  await page.evaluate(() => window.__triggerBackButton());
  await expect(page.locator("#q-index")).toContainText("১");
  state = await page.evaluate(() => window.__mobileQa);
  expect(state.backVisible).toBe(false);
});
