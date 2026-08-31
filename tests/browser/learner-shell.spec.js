const { test, expect } = require("@playwright/test");

const {
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  installApiMocks,
  installTelegramMock,
} = require("./fixtures");

const SURFACES = [
  { path: "/dashboard.html", active: "অগ্রগতি", minHeight: 436 },
  { path: "/mock.html", active: "কুইজ", minHeight: 456 },
  { path: "/syllabus.html", active: "অগ্রগতি", minHeight: 456 },
];

const PRIMARY_LEARNER_SURFACES = [
  "/",
  "/practice.html?source=due",
  "/dashboard.html",
  "/settings.html",
  "/mock.html",
  "/syllabus.html",
];

test("primary learner surfaces share safe-area metadata and Citizen Affairs identity", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);

  for (const path of PRIMARY_LEARNER_SURFACES) {
    await page.goto(path);
    await expect(page.locator('meta[name="viewport"]'), path).toHaveAttribute(
      "content",
      /viewport-fit=cover/,
    );
    await expect(page.locator(".wordmark"), path).toHaveText("CITIZEN AFFAIRS বাংলা");
  }
});

test("learner shells preserve branding, safe areas, and fixed-nav clearance", async ({
  page,
}) => {
  await installTelegramMock(page);
  await installApiMocks(page);

  for (const surface of SURFACES) {
    await page.goto(surface.path);

    await expect(page.locator('meta[name="viewport"]')).toHaveAttribute(
      "content",
      /viewport-fit=cover/,
    );
    await expect(page.locator(".wordmark")).toHaveText("CITIZEN AFFAIRS বাংলা");
    if (surface.active) {
      await expect(page.locator("nav.bottom a.active")).toHaveAttribute(
        "aria-current",
        "page",
      );
      await expect(page.locator("nav.bottom a.active")).toContainText(surface.active);
    } else {
      await expect(page.locator("nav.bottom a.active")).toHaveCount(0);
    }

    const geometry = await page.evaluate(() => {
      const root = document.documentElement;
      root.style.setProperty("--tg-content-safe-area-inset-top", "20px");
      root.style.setProperty("--tg-content-safe-area-inset-right", "9px");
      root.style.setProperty("--tg-content-safe-area-inset-bottom", "34px");
      root.style.setProperty("--tg-content-safe-area-inset-left", "7px");
      root.style.setProperty("--miniapp-viewport-height", "540px");
      root.style.setProperty("--miniapp-viewport-stable-height", "550px");

      const main = document.querySelector("main");
      const nav = document.querySelector("nav.bottom");
      const navLink = nav.querySelector("a");
      const mainStyle = getComputedStyle(main);
      const navStyle = getComputedStyle(nav);
      return {
        mainMinHeight: Number.parseFloat(mainStyle.minHeight),
        mainPaddingTop: Number.parseFloat(mainStyle.paddingTop),
        mainPaddingLeft: Number.parseFloat(mainStyle.paddingLeft),
        navBottomGap: window.innerHeight - nav.getBoundingClientRect().bottom,
        navPaddingBottom: Number.parseFloat(navStyle.paddingBottom),
        navFontSize: Number.parseFloat(getComputedStyle(navLink).fontSize),
      };
    });

    expect(geometry.mainMinHeight).toBe(surface.minHeight);
    expect(geometry.mainPaddingTop).toBeGreaterThanOrEqual(30);
    expect(geometry.mainPaddingLeft).toBeGreaterThanOrEqual(17);
    expect(Math.max(geometry.navBottomGap, geometry.navPaddingBottom)).toBeGreaterThanOrEqual(
      34,
    );
    expect(geometry.navFontSize).toBeGreaterThanOrEqual(11);

    await assertNoHorizontalOverflow(page);
    await assertBottomNavigationDoesNotCoverContent(page);
  }
});
