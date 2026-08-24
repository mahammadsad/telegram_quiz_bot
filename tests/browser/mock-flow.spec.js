const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const {
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  installTelegramMock,
} = require("./fixtures");

const TEST_ID = "11111111-1111-4111-8111-111111111111";
const ATTEMPT_ID = "22222222-2222-4222-8222-222222222222";
const SECTION_ONE = "33333333-3333-4333-8333-333333333331";
const SECTION_TWO = "33333333-3333-4333-8333-333333333332";

async function expectWcag22Aa(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

function question(id, order, text) {
  return {
    questionId: `44444444-4444-4444-8444-${String(id).padStart(12, "0")}`,
    order,
    sectionOrder: order,
    question: text,
    options: ["প্রথম বিকল্প", "দ্বিতীয় বিকল্প", "তৃতীয় বিকল্প", "চতুর্থ বিকল্প"],
    subjectKey: id < 3 ? "mathematics" : "reasoning",
    topic: id < 3 ? "সংখ্যা" : "যুক্তি",
    marksForCorrect: 1,
    negativeMarksForWrong: 0.25,
    required: true,
  };
}

function testInstance() {
  return {
    testInstanceId: TEST_ID,
    title: "WBCS পূর্ণ মক পরীক্ষা",
    status: "open",
    testType: "full_mock",
    questionCount: 4,
    totalMarks: 4,
    timeLimitSeconds: 1800,
    sections: [
      {
        sectionInstanceId: SECTION_ONE,
        sectionKey: "mathematics",
        displayName: "গণিত",
        order: 1,
        questionCount: 2,
        timeLimitSeconds: 900,
        allowMarkForReview: true,
        questions: [question(1, 1, "গণিতের প্রথম প্রশ্ন"), question(2, 2, "গণিতের দ্বিতীয় প্রশ্ন")],
      },
      {
        sectionInstanceId: SECTION_TWO,
        sectionKey: "reasoning",
        displayName: "রিজনিং",
        order: 2,
        questionCount: 2,
        timeLimitSeconds: 900,
        allowMarkForReview: true,
        questions: [question(3, 1, "রিজনিংয়ের প্রথম প্রশ্ন"), question(4, 2, "রিজনিংয়ের দ্বিতীয় প্রশ্ন")],
      },
    ],
  };
}

async function installMockAttemptApi(page, { failFirstProgress = false } = {}) {
  const state = {
    bookmarks: [],
    starts: [],
    progress: [],
    submits: [],
    currentSection: SECTION_ONE,
    failFirstProgress,
  };
  await page.route("**/api/me/bookmarks", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") return route.fallback();
    const body = request.postDataJSON();
    state.bookmarks.push(body);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ active: true }),
    });
  });
  await page.route("**/api/tests/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });
    if (request.method() === "GET" && path === "/api/tests/catalog") {
      return json({ rows: [{
        testInstanceId: TEST_ID,
        title: "WBCS পূর্ণ মক পরীক্ষা",
        testType: "full_mock",
        examKey: "WBCS",
        examName: "WBCS",
        subjectKey: "mixed",
        questionCount: 4,
        timeLimitSeconds: 1800,
        negativeMarksPerWrong: 0.25,
        availability: "open",
      }] });
    }
    if (request.method() === "GET" && path === "/api/tests/attempts/recent") {
      return json({ count: 1, rows: [{
        attemptId: ATTEMPT_ID,
        testInstanceId: TEST_ID,
        clientAttemptId: ATTEMPT_ID,
        status: "in_progress",
        questionCount: 4,
        answeredCount: 2,
        netMarks: 0,
      }] });
    }
    if (request.method() === "GET" && path === `/api/tests/instances/${TEST_ID}`) {
      return json(testInstance());
    }
    if (request.method() === "POST" && path.endsWith("/attempts/start")) {
      const body = request.postDataJSON();
      state.starts.push(body);
      return json({
        attemptId: ATTEMPT_ID,
        testInstanceId: TEST_ID,
        status: "in_progress",
        clientAttemptId: body.clientAttemptId,
        currentSectionInstanceId: state.currentSection,
        deadlineAt: "2099-08-08T13:00:00Z",
        sections: [
          { sectionInstanceId: SECTION_ONE, order: 1, status: state.currentSection === SECTION_ONE ? "open" : "completed", deadlineAt: "2099-08-08T12:45:00Z" },
          { sectionInstanceId: SECTION_TWO, order: 2, status: state.currentSection === SECTION_TWO ? "open" : "locked", deadlineAt: state.currentSection === SECTION_TWO ? "2099-08-08T13:00:00Z" : null },
        ],
        responses: state.progress.at(-1)?.responses || [],
      });
    }
    if (request.method() === "PUT" && path.endsWith("/progress")) {
      const body = request.postDataJSON();
      state.progress.push(body);
      if (state.failFirstProgress) {
        state.failFirstProgress = false;
        return json({ detail: "temporary" }, 503);
      }
      return json({ attemptId: ATTEMPT_ID, status: "in_progress", responses: body.responses });
    }
    if (request.method() === "POST" && path.endsWith("/sections/advance")) {
      state.currentSection = request.postDataJSON().nextSectionInstanceId;
      return json({ attemptId: ATTEMPT_ID, status: "in_progress", currentSectionInstanceId: state.currentSection });
    }
    if (request.method() === "POST" && path.endsWith("/submit")) {
      const body = request.postDataJSON();
      state.submits.push(body);
      return json({
        attemptId: ATTEMPT_ID,
        status: body.autoSubmit ? "auto_submitted" : "submitted",
        netMarks: 1.5,
        negativeMarks: 0.5,
        correct: 2,
        wrong: 2,
        skipped: 0,
        rankCohort: { rank: 7, size: 40, eligible: true },
        sections: [
          { sectionKey: "mathematics", displayName: "গণিত", correct: 1, skipped: 0, netMarks: 0.75 },
          { sectionKey: "reasoning", displayName: "রিজনিং", correct: 1, skipped: 0, netMarks: 0.75 },
        ],
        topicAnalysis: [
          { subjectKey: "mathematics", topic: "সংখ্যা", correct: 1, wrong: 1, netMarks: 0.75 },
          { subjectKey: "reasoning", topic: "যুক্তি", correct: 1, wrong: 1, netMarks: 0.75 },
        ],
      });
    }
    return json({ detail: `Unhandled mock API: ${request.method()} ${path}` }, 404);
  });
  return state;
}

test("timed multi-section mock persists, resumes, advances, and renders analysis", async ({ page }) => {
  await installTelegramMock(page);
  const api = await installMockAttemptApi(page);
  await page.goto(`/mock.html?test=${TEST_ID}`);

  await expect(page.locator("#screen-intro")).toBeVisible();
  await expect(page.locator("#intro-title")).toHaveText("WBCS পূর্ণ মক পরীক্ষা");
  await expect(page.locator("#intro-sections")).toHaveText("2");
  await page.locator("#btn-start").click();
  await expect(page.locator("#screen-test")).toBeVisible();
  await expect(page.locator("#section-title")).toHaveText("গণিত");
  await expect(page.locator("#timer")).not.toHaveText("--:--");

  await page.locator("#btn-bookmark").click();
  await expect(page.locator("#btn-bookmark")).toContainText("অনুশীলনে যোগ হয়েছে");
  expect(api.bookmarks).toEqual([{
    initData: "deterministic-browser-test",
    itemType: "question",
    itemId: question(1, 1, "").questionId,
    active: true,
  }]);

  await page.locator(".option").nth(1).click();
  await page.locator("#mark-review").check();
  await expect(page.locator("#sync-status")).toContainText("সিঙ্ক হয়েছে");
  const firstDraft = await page.evaluate((id) => JSON.parse(localStorage.getItem(`telegram-mock-draft:${id}`)), TEST_ID);
  expect(firstDraft.answers).toBeTruthy();
  expect(JSON.stringify(firstDraft)).not.toContain("deterministic-browser-test");
  expect(JSON.stringify(firstDraft)).not.toContain("correctIndex");

  await page.reload();
  await expect(page.locator("#resume-box")).toBeVisible();
  await page.locator("#btn-resume").click();
  await expect(page.locator("#screen-test")).toBeVisible();
  expect(api.starts).toHaveLength(2);
  expect(api.starts[1].clientAttemptId).toBe(api.starts[0].clientAttemptId);

  await page.locator("#btn-section").click();
  await expect(page.locator("#section-title")).toHaveText("রিজনিং");
  await page.locator(".option").first().click();
  await page.locator("#btn-submit").click();
  await expect(page.locator("#submit-modal")).toBeVisible();
  await page.locator("#btn-submit-confirm").click();
  await expect(page.locator("#screen-result")).toBeVisible();
  await expect(page.locator("#result-net")).toHaveText("1.5");
  await expect(page.locator("#result-rank")).toHaveText("7 / 40");
  await expect(page.locator("#section-analysis .analysis-row")).toHaveCount(2);
  await expect(page.locator("#topic-analysis")).toContainText("সংখ্যা");
  expect(api.submits).toEqual([{ initData: "deterministic-browser-test", autoSubmit: false }]);
  await expectWcag22Aa(page);

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("failed progress sync keeps the local draft and exposes retry", async ({ page }) => {
  await installTelegramMock(page);
  const api = await installMockAttemptApi(page, { failFirstProgress: true });
  await page.goto(`/mock.html?test=${TEST_ID}`);
  await page.locator("#btn-start").click();
  await page.locator(".option").first().click();

  await expect(page.locator("#sync-status")).toContainText("খসড়া নিরাপদ আছে");
  await expect(page.locator("#btn-sync-retry")).toBeVisible();
  const draft = await page.evaluate((id) => localStorage.getItem(`telegram-mock-draft:${id}`), TEST_ID);
  expect(draft).toContain("answers");

  await page.locator("#btn-sync-retry").click();
  await expect(page.locator("#sync-status")).toContainText("সিঙ্ক হয়েছে");
  expect(api.progress.length).toBeGreaterThanOrEqual(2);
});

test("authenticated catalog shows server attempt state and resumes across devices", async ({ page }) => {
  await installTelegramMock(page);
  const api = await installMockAttemptApi(page);
  await page.goto("/mock.html");

  await expect(page.locator("#screen-catalog")).toBeVisible();
  await expect(page.locator(".catalog-item")).toContainText("2 / 4 উত্তর · অসম্পূর্ণ");
  const resume = page.getByRole("link", { name: "চালিয়ে যান" });
  await expect(resume).toHaveAttribute("href", new RegExp(`test=${TEST_ID}.*clientAttempt=${ATTEMPT_ID}`));
  await resume.click();

  await expect(page.locator("#screen-intro")).toBeVisible();
  await expect(page.locator("#resume-box")).toBeVisible();
  await page.locator("#btn-resume").click();
  await expect(page.locator("#screen-test")).toBeVisible();
  expect(api.starts).toHaveLength(1);
  expect(api.starts[0].clientAttemptId).toBe(ATTEMPT_ID);
});
