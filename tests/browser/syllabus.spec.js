const { test, expect } = require("@playwright/test");

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
  await expect(page.locator(".chapter").first()).toContainText("দৈনিক কুইজে আছে");
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
