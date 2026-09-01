const { test, expect } = require("@playwright/test");

const {
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

const MOBILE_ACCEPTANCE_SCENARIOS = [
  {
    name: "320x568 with Telegram 34px content inset",
    viewport: { width: 320, height: 568 },
    stableHeight: 568,
  },
  {
    // Chromium does not expose browser chrome zoom through Playwright. A
    // 1280x800 viewport at 200% zoom has this 640x400 effective CSS layout.
    name: "200% zoom-equivalent 1280x800 layout",
    viewport: { width: 640, height: 400 },
    stableHeight: 400,
  },
  {
    // Resizing keeps the test deterministic while exercising the same CSS
    // constraints as Telegram's reduced visual viewport above an open keyboard.
    name: "keyboard-like reduced visual viewport",
    viewport: { width: 320, height: 340 },
    stableHeight: 568,
  },
];

async function setMobileAcceptanceEnvironment(page, scenario) {
  const synchronizeTelegramViewport = async () =>
    page.evaluate(({ height, stableHeight }) => {
      const webApp = window.Telegram?.WebApp;
      if (webApp) {
        webApp.safeAreaInset = { top: 0, right: 0, bottom: 34, left: 0 };
        webApp.contentSafeAreaInset = { top: 0, right: 0, bottom: 34, left: 0 };
        webApp.viewportHeight = height;
        webApp.viewportStableHeight = stableHeight;
      }
      const root = document.documentElement;
      root.style.setProperty("--tg-safe-area-inset-bottom", "34px");
      root.style.setProperty("--tg-content-safe-area-inset-bottom", "34px");
      root.style.setProperty("--miniapp-viewport-height", `${height}px`);
      root.style.setProperty("--miniapp-viewport-stable-height", `${stableHeight}px`);
    }, { height: scenario.viewport.height, stableHeight: scenario.stableHeight });

  await synchronizeTelegramViewport();
  await page.setViewportSize(scenario.viewport);
  await synchronizeTelegramViewport();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve())));
  await page.evaluate(({ height, stableHeight }) => {
    const root = document.documentElement;
    root.style.setProperty("--tg-safe-area-inset-bottom", "34px");
    root.style.setProperty("--tg-content-safe-area-inset-bottom", "34px");
    root.style.setProperty("--miniapp-viewport-height", `${height}px`);
    root.style.setProperty("--miniapp-viewport-stable-height", `${stableHeight}px`);
  }, { height: scenario.viewport.height, stableHeight: scenario.stableHeight });
}

async function expectSingleActionSurfaceAcrossMobileMatrix(
  page,
  { actionSelector = null, nativeAction = false },
) {
  for (const scenario of MOBILE_ACCEPTANCE_SCENARIOS) {
    await test.step(scenario.name, async () => {
      await setMobileAcceptanceEnvironment(page, scenario);
      if (actionSelector) {
        const action = page.locator(actionSelector);
        await expect(action).toBeVisible();
        await action.evaluate((element) => element.scrollIntoView({ block: "center" }));
      }

      const layout = await page.evaluate((selector) => {
        const visible = (element) => {
          if (!element) return false;
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            rect.width > 0 &&
            rect.height > 0
          );
        };
        const rectOf = (element) => {
          const rect = element.getBoundingClientRect();
          return {
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            left: rect.left,
            width: rect.width,
            height: rect.height,
          };
        };
        const actionElement = selector ? document.querySelector(selector) : null;
        const domSurfaces = Array.from(
          document.querySelectorAll(
            ".bottom-nav, nav.bottom, #screen-quiz .browser-only, #next-wrap, .selector-dialog[open] .dialog-actions",
          ),
        ).filter(visible);
        const nativeMainVisible = Boolean(window.__mobileQa?.mainVisible);
        const surfaces = domSurfaces.map((surface) => ({
          name:
            surface.id ||
            (surface.matches(".bottom-nav") ? "bottom-nav" : surface.className),
          containsAction: surface.contains(actionElement),
          rect: rectOf(surface),
        }));
        if (nativeMainVisible) {
          surfaces.push({ name: "telegram-main-button", containsAction: false, rect: null });
        }
        const actionRect = actionElement ? rectOf(actionElement) : null;
        const overlaps = surfaces
          .filter((surface) => actionRect && surface.rect && !surface.containsAction)
          .filter(
            (surface) =>
              actionRect.right > surface.rect.left &&
              actionRect.left < surface.rect.right &&
              actionRect.bottom > surface.rect.top &&
              actionRect.top < surface.rect.bottom,
          )
          .map((surface) => surface.name);
        return {
          actionRect,
          documentWidth: document.documentElement.scrollWidth,
          mainButtonText: window.__mobileQa?.mainParams?.text || "",
          nativeMainVisible,
          overlaps,
          safeBottom: getComputedStyle(document.documentElement)
            .getPropertyValue("--tg-content-safe-area-inset-bottom")
            .trim(),
          surfaces,
          viewport: { width: window.innerWidth, height: window.innerHeight },
        };
      }, actionSelector);

      expect(layout.safeBottom, scenario.name).toBe("34px");
      expect(layout.documentWidth, scenario.name).toBeLessThanOrEqual(
        layout.viewport.width + 1,
      );
      expect(layout.surfaces, scenario.name).toHaveLength(1);
      if (layout.actionRect) {
        expect(layout.actionRect.left, scenario.name).toBeGreaterThanOrEqual(0);
        expect(layout.actionRect.right, scenario.name).toBeLessThanOrEqual(
          layout.viewport.width + 1,
        );
        expect(layout.actionRect.top, scenario.name).toBeGreaterThanOrEqual(0);
        expect(layout.actionRect.bottom, scenario.name).toBeLessThanOrEqual(
          layout.viewport.height - 34 + 1,
        );
      }
      expect(layout.overlaps, scenario.name).toEqual([]);
      if (nativeAction) {
        expect(layout.nativeMainVisible, scenario.name).toBe(true);
        expect(layout.mainButtonText.trim(), scenario.name).not.toBe("");
      }
    });
  }
}

test("quiz loading, keyboard navigation, reduced motion, and mobile layout are accessible", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installTelegramMock(page);
  await installApiMocks(page, { quizLoadDelayMs: 1000 });

  const navigation = page.goto(`/index.html?quiz=${QUIZ_ID}`);
  await expect(page.locator("#screen-loading")).toBeVisible();
  await expect(page.locator("#loading-message")).toContainText("লোড হচ্ছে");
  await navigation;
  await expect(page.locator("#screen-intro")).toBeVisible();
  const skipLink = page.locator(".skip-link");
  await expect(skipLink).toHaveCount(1);
  await expect(skipLink).not.toBeInViewport();
  await skipLink.focus();
  await expect(skipLink).toBeInViewport();
  await expect(skipLink).toContainText("মূল অংশে যান");

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

  await page.locator("#question-map-toggle").click();
  await expect(page.locator("#question-map-sheet")).toBeVisible();
  await page.keyboard.press("Tab");
  const focusedQuestion = page.locator(".nav-q:focus");
  await expect(focusedQuestion).toHaveCount(1);
  const focusStyle = await focusedQuestion.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
    };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);

  await expect(page.locator(".nav-q").first()).toHaveAttribute("aria-current", "step");
  await page.keyboard.press("Escape");
  await expect(page.locator("#question-map-sheet")).toBeHidden();
  await expect(page.locator("#question-map-toggle")).toBeFocused();

  await assertNoHorizontalOverflow(page);
  await assertVisibleTouchTargets(page);
  await assertBottomNavigationDoesNotCoverContent(page);
});

test("active quiz keeps one safe current action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto(`/index.html?quiz=${QUIZ_ID}`);
  await expect(page.locator("#screen-intro")).toBeVisible();
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#screen-quiz")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    actionSelector: "#question-map-toggle",
    nativeAction: true,
  });
});

test("practice feedback keeps one safe next action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  await page.goto("/practice.html?source=due");
  await expect(page.locator("#practice")).toBeVisible();
  await page.locator(".option").first().click();
  await page.evaluate(() => window.__triggerMainButton());
  await expect(page.locator("#feedback")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    nativeAction: true,
  });
});

test("practice auth error keeps one safe recovery action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due" });
  await page.route(/\/api\/me\/practice-bootstrap(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "private diagnostic" }),
    }),
  );
  await page.goto("/practice.html?source=due");
  await expect(page.locator("#error")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    actionSelector: "#auth-reopen",
  });
});

test("practice empty state keeps one safe next action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due", emptyPractice: true });
  await page.goto("/practice.html?source=due");
  await expect(page.locator("#empty")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    actionSelector: "#empty .primary",
  });
});

test("practice completed state keeps one safe next action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page, { practiceSource: "due", practiceCorrect: true });
  await page.goto("/practice.html?source=due");
  await expect(page.locator("#practice")).toBeVisible();
  for (let index = 0; index < 2; index += 1) {
    await page.locator(".option").first().click();
    await page.evaluate(() => window.__triggerMainButton());
    await expect(page.locator("#feedback")).toBeVisible();
    await page.evaluate(() => window.__triggerMainButton());
  }
  await expect(page.locator("#completed")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    actionSelector: "#completed .primary",
  });
});

test("open settings dialog keeps one safe action across the mobile acceptance matrix", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);
  await page.goto("/settings.html");
  await expect(page.locator("#settings")).toBeVisible();
  await page.locator("#open-subject-dialog").click();
  await expect(page.locator("#subject-dialog")).toBeVisible();

  await expectSingleActionSurfaceAcrossMobileMatrix(page, {
    actionSelector: "#subject-done",
  });
});
