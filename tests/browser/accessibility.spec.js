const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const {
  QUIZ_ID,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

async function expectWcag22Aa(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test("Bengali preparation hub satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page, { startParam: "" });
  await installApiMocks(page);
  await page.goto("/");

  await expect(page.locator("#screen-home")).toBeVisible();
  await expectWcag22Aa(page);
});

test("quiz start experience satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);

  await expect(page.locator("#screen-intro")).toBeVisible();
  await expectWcag22Aa(page);
});

test("active quiz and open question map satisfy automated WCAG 2.2 AA checks", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);

  await expect(page.locator("#screen-intro")).toBeVisible();
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#screen-quiz")).toBeVisible();
  await expect(page.locator(".option")).toHaveCount(4);
  await expectWcag22Aa(page);

  await page.locator("#question-map-toggle").click();
  await expect(page.locator("#question-map-sheet")).toBeVisible();
  await expect(page.locator("#question-map-toggle")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expectWcag22Aa(page);
});

test("dashboard satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/dashboard.html");

  await expect(page.locator("#content")).toBeVisible();
  await expectWcag22Aa(page);
});

test("settings satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/settings.html");

  await expect(page.locator("#settings")).toBeVisible();
  await expectWcag22Aa(page);
});

test("open settings subject and exam dialogs satisfy automated WCAG 2.2 AA checks", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/settings.html");

  await expect(page.locator("#settings")).toBeVisible();
  await page.locator("#open-subject-dialog").click();
  await expect(page.locator("#subject-dialog")).toBeVisible();
  await expect(page.locator("#subject-checks input")).toHaveCount(13);
  await expectWcag22Aa(page);

  await page.locator("#subject-dialog-close").click();
  await expect(page.locator("#subject-dialog")).toBeHidden();
  await page.locator("#open-exam-dialog").click();
  await expect(page.locator("#exam-dialog")).toBeVisible();
  await expect(page.locator("#exam-checks input")).toHaveCount(11);
  await expectWcag22Aa(page);
});

test("syllabus map satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/syllabus.html");

  await expect(page.locator("#catalog")).toBeVisible();
  await expectWcag22Aa(page);
});

test("revision practice satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, { practiceSource: "due" });
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#practice")).toBeVisible();
  await expectWcag22Aa(page);
});

test("practice feedback satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, { practiceSource: "due" });
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#practice")).toBeVisible();
  await page.locator(".option").first().click();
  await page.locator("#submit").click();
  await expect(page.locator("#feedback")).toBeVisible();
  await expect(page.locator("#feedback")).toContainText("সঠিক উত্তর");
  await expectWcag22Aa(page);
});

test("practice authentication error satisfies automated WCAG 2.2 AA checks", async ({
  page,
}) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, { practiceSource: "due" });
  await page.route(/\/api\/me\/practice-bootstrap(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      headers: { "X-Request-ID": "accessibility-auth-401" },
      body: JSON.stringify({ detail: "private diagnostic" }),
    }),
  );
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#error")).toBeVisible();
  await expect(page.locator("#error")).toHaveAttribute("data-state", "auth_expired");
  await expect(page.locator("#count")).toHaveText("—");
  await expectWcag22Aa(page);
});

test("practice empty state satisfies automated WCAG 2.2 AA checks", async ({ page }) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, {
    practiceSource: "due",
    emptyPractice: true,
  });
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#empty")).toBeVisible();
  await expect(page.locator("#completed")).toBeHidden();
  await expect(page.locator("#count")).toHaveText("০");
  await expectWcag22Aa(page);
});

test("practice completed state satisfies automated WCAG 2.2 AA checks", async ({
  page,
}) => {
  await installTelegramMock(page, { nativeActions: false });
  await installApiMocks(page, {
    practiceSource: "due",
    practiceCorrect: true,
  });
  await page.goto("/practice.html?source=due");

  await expect(page.locator("#practice")).toBeVisible();
  for (let index = 0; index < 2; index += 1) {
    await page.locator(".option").first().click();
    await page.locator("#submit").click();
    await expect(page.locator("#feedback")).toBeVisible();
    await page.locator("#next").click();
  }
  await expect(page.locator("#completed")).toBeVisible();
  await expect(page.locator("#empty")).toBeHidden();
  await expect(page.locator("#completed-count")).toHaveText("২");
  await expectWcag22Aa(page);
});
