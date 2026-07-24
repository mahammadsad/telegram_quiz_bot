const { test, expect } = require("@playwright/test");

const {
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

test("quiz loading, keyboard navigation, reduced motion, and mobile layout are accessible", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installTelegramMock(page);
  await installApiMocks(page, { quizLoadDelayMs: 250 });

  const navigation = page.goto(`/index.html?quiz=${QUIZ_ID}`);
  await expect(page.locator("#screen-loading")).toBeVisible();
  await expect(page.locator("#loading-message")).toContainText("লোড হচ্ছে");
  await navigation;
  await expect(page.locator("#screen-intro")).toBeVisible();

  const reducedMotion = await page.evaluate(() => {
    const loader = getComputedStyle(document.querySelector(".loader"));
    const progress = getComputedStyle(document.querySelector(".progress-fill"));
    return {
      animationName: loader.animationName,
      animationDuration: loader.animationDuration,
      transitionDuration: progress.transitionDuration,
      mediaMatches: matchMedia("(prefers-reduced-motion: reduce)").matches,
    };
  });
  expect(reducedMotion.mediaMatches).toBe(true);
  expect(reducedMotion.animationName).toBe("none");
  expect(reducedMotion.animationDuration).toBe("0s");
  expect(reducedMotion.transitionDuration).toBe("0s");

  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#screen-quiz")).toBeVisible();
  await page.keyboard.press("1");
  await expect(page.locator(".option").first()).toHaveClass(/selected/);
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#q-index")).toContainText("২");
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator("#q-index")).toContainText("১");

  await page.locator(".nav-q").nth(2).focus();
  const focusStyle = await page.locator(".nav-q").nth(2).evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
    };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});
