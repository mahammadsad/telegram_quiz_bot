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

test("syllabus map exposes the reviewed hierarchy and honest availability", async ({
  page,
}, testInfo) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/syllabus.html?exam=WBCS");

  await expect(page.locator("#catalog .subject-card")).toHaveCount(2);
  await expect(page.locator("#summary")).toContainText("২টি বিষয়");
  await expect(page.locator("#personal-progress")).toBeVisible();
  await expect(page.locator("#progress-copy")).toContainText("৫ / ৮টি");
  await expect(page.locator(".topic-progress.mastered")).toContainText("আয়ত্ত");
  await expect(page.locator(".topic-progress.in-progress")).toContainText("পুনরাবৃত্তি");
  await expect(page.locator(".chapter").first()).toContainText("দৈনিক রোটেশনে");
  await expect(page.locator(".chapter").nth(1)).toContainText("সিলেবাসে আছে");

  await page.locator("#topic-search").fill("ফরাসি বিপ্লব");
  await expect(page.locator("#catalog .subject-card")).toHaveCount(1);
  await expect(page.locator(".chapter")).toHaveCount(1);
  await expect(page.locator(".chapter")).toHaveAttribute("open", "");
  await expect(page.locator(".topics")).toContainText("ফরাসি বিপ্লব");

  await expect(page.getByRole("link", { name: "এই বিষয়ের কুইজ" })).toHaveAttribute(
    "href",
    "./?subject=history",
  );
  await capture(page, testInfo, "syllabus-map");
  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("syllabus map provides a recoverable empty filter state", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/syllabus.html");

  await page.locator("#topic-search").fill("কোনো-মিল-নেই");
  await expect(page.locator("#empty")).toBeVisible();
  await page.locator("#clear-filters").click();
  await expect(page.locator("#catalog .subject-card")).toHaveCount(2);
});

test("public syllabus discovery does not invent private progress", async ({ page }) => {
  await installTelegramMock(page, { requireLaunchHash: true });
  await installApiMocks(page);
  await page.goto("/syllabus.html");

  await expect(page.locator("#catalog .subject-card")).toHaveCount(2);
  await expect(page.locator("#personal-progress")).toBeHidden();
  await expect(page.locator(".topic-progress")).toHaveCount(0);
});

test("slow or failed private progress leaves syllabus usable and can retry independently", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  let releaseProgress;
  const pending = new Promise((resolve) => { releaseProgress = resolve; });
  let rejectProgress = true;
  let catalogRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/syllabus") catalogRequests += 1;
  });
  await page.route("**/api/me/syllabus-progress", async (route) => {
    if (!rejectProgress) return route.fallback();
    await pending;
    return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "expired" }) });
  });
  try {
    await page.goto("/syllabus.html");
    await expect(page.locator("#catalog .subject-card")).toHaveCount(2);
    await page.locator("#topic-search").fill("ফরাসি বিপ্লব");
    await expect(page.locator(".chapter")).toHaveCount(1);
    releaseProgress();
    await expect(page.locator("#progress-retry")).toBeVisible();
    await expect(page.locator("#personal-progress")).toBeHidden();
    await expect(page.locator("#progress-notice-copy")).not.toContainText("expired");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations).toEqual([]);
    await assertNoHorizontalOverflow(page);
    rejectProgress = false;
    await page.locator("#progress-retry").click();
    await expect(page.locator("#personal-progress")).toBeVisible();
    await expect(page.locator("#progress-notice")).toBeHidden();
    await expect(page.locator("#topic-search")).toHaveValue("ফরাসি বিপ্লব");
    await expect(page.locator(".chapter")).toHaveCount(1);
    expect(catalogRequests).toBe(1);
  } finally {
    releaseProgress();
  }
});

test("late progress updates preserve an open chapter and keyboard focus", async ({ page }) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  let releaseProgress;
  const pending = new Promise((resolve) => { releaseProgress = resolve; });
  await page.route("**/api/me/syllabus-progress", async (route) => {
    await pending;
    return route.fallback();
  });
  try {
    await page.goto("/syllabus.html");
    const chapter = page.locator(".chapter").first();
    await chapter.locator("summary").click();
    await chapter.locator("summary").focus();
    releaseProgress();
    await expect(page.locator("#personal-progress")).toBeVisible();
    await expect(page.locator(".topic-progress.mastered")).toContainText("আয়ত্ত");
    await expect(chapter).toHaveAttribute("open", "");
    await expect(chapter.locator("summary")).toBeFocused();
  } finally {
    releaseProgress();
  }
});
