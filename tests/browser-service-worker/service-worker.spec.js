const { test, expect } = require("@playwright/test");

const ACTIVE_SHELL_CACHE = "quiz-miniapp-shell-v8.7.8-ui1";

async function openHarness(page) {
  await page.goto("/tests/browser-service-worker/harness.html");
  await expect.poll(
    () => page.evaluate(() => window.isSecureContext),
  ).toBe(true);
}

async function registerAndControl(page) {
  await page.evaluate(async () => {
    const controlled = new Promise((resolve) => {
      if (navigator.serviceWorker.controller) {
        resolve();
        return;
      }
      navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true });
    });
    await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    await controlled;
  });
  await expect.poll(
    () => page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
  ).toBe(true);
}

test("sensitive API reads bypass service-worker interception, cache, and its historical deadline", async ({ page }) => {
  test.setTimeout(25_000);
  await openHarness(page);
  await registerAndControl(page);
  const sensitiveResponseOrigins = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === "/api/me/dashboard") {
      sensitiveResponseOrigins.push(response.fromServiceWorker());
    }
  });

  const result = await page.evaluate(async () => {
    const probe = crypto.randomUUID();
    const url = `/api/me/dashboard?probe=${probe}&delayFirstMs=8500`;
    const startedAt = performance.now();
    const firstResponse = await fetch(url, { cache: "no-store" });
    const first = await firstResponse.json();
    const elapsedMs = performance.now() - startedAt;
    const secondResponse = await fetch(url, { cache: "no-store" });
    const second = await secondResponse.json();
    const cacheNames = await caches.keys();
    const cachedSensitiveUrls = [];
    for (const cacheName of cacheNames) {
      const cache = await caches.open(cacheName);
      const keys = await cache.keys();
      cachedSensitiveUrls.push(...keys
        .map((request) => request.url)
        .filter((cachedUrl) => cachedUrl.includes(probe)));
    }
    return {
      controlled: Boolean(navigator.serviceWorker.controller),
      elapsedMs,
      firstStatus: firstResponse.status,
      first,
      secondStatus: secondResponse.status,
      second,
      cachedSensitiveUrls,
    };
  });

  expect(result.controlled).toBe(true);
  expect(result.elapsedMs).toBeGreaterThanOrEqual(8_000);
  expect(result.firstStatus).toBe(200);
  expect(result.secondStatus).toBe(200);
  expect(result.first).toMatchObject({
    kind: "sensitive-network-response",
    requestCount: 1,
  });
  expect(result.second).toMatchObject({
    kind: "sensitive-network-response",
    requestCount: 2,
  });
  expect(sensitiveResponseOrigins).toEqual([false, false]);
  expect(result.cachedSensitiveUrls).toEqual([]);
});

test("a 24-second cold quiz read succeeds with the page as the only API deadline owner", async ({ page }) => {
  test.setTimeout(40_000);
  await openHarness(page);
  await registerAndControl(page);
  await page.addScriptTag({ url: "/miniapp-shell.js" });

  const result = await page.evaluate(async () => {
    const probe = crypto.randomUUID();
    const url = `/api/quiz/sw-${probe}?probe=${probe}&delayFirstMs=24000&answerFree=1`;
    const startedAt = performance.now();
    const payload = await window.miniappRequest(url, { miniappRetryDelayMs: 0 });
    return {
      elapsedMs: performance.now() - startedAt,
      payload,
    };
  });

  expect(result.elapsedMs).toBeGreaterThanOrEqual(23_500);
  expect(result.payload).toMatchObject({
    kind: "answer-free-network-response",
    requestCount: 1,
  });
});

test("answer-free projections enter the fallback cache only with the opt-in response header", async ({ page }) => {
  await openHarness(page);
  await registerAndControl(page);

  const result = await page.evaluate(async () => {
    async function exercise(answerFree) {
      const probe = crypto.randomUUID();
      const url = `/api/quiz/sw-${probe}?probe=${probe}&answerFree=${answerFree ? "1" : "0"}&failAfter=1`;
      const firstResponse = await fetch(url, { cache: "no-store" });
      const first = await firstResponse.json();
      const cache = await caches.open("quiz-answer-free-v8.7.8-ui1");
      const cachedAfterSuccess = Boolean(await cache.match(url));
      const secondResponse = await fetch(url, { cache: "no-store" });
      const second = await secondResponse.json();
      return {
        cachedAfterSuccess,
        firstStatus: firstResponse.status,
        first,
        secondStatus: secondResponse.status,
        second,
      };
    }

    return {
      withoutHeader: await exercise(false),
      withHeader: await exercise(true),
    };
  });

  expect(result.withoutHeader.cachedAfterSuccess).toBe(false);
  expect(result.withoutHeader.firstStatus).toBe(200);
  expect(result.withoutHeader.secondStatus).toBe(503);
  expect(result.withoutHeader.second.kind).toBe("deliberate-upstream-failure");

  expect(result.withHeader.cachedAfterSuccess).toBe(true);
  expect(result.withHeader.firstStatus).toBe(200);
  expect(result.withHeader.secondStatus).toBe(200);
  expect(result.withHeader.second).toEqual(result.withHeader.first);
});

test("shell requests refresh stale cached assets from the network", async ({ page }) => {
  await openHarness(page);
  await registerAndControl(page);

  const result = await page.evaluate(async () => {
    const cache = await caches.open("quiz-miniapp-shell-v8.7.8-ui1");
    await cache.put(
      "/index.js",
      new Response("stale-cache-only-script", {
        status: 200,
        headers: { "Content-Type": "text/javascript" },
      }),
    );
    const response = await fetch("/index.js", { cache: "no-store" });
    const body = await response.text();
    const refreshed = await cache.match("/index.js");
    return {
      body,
      cachedBody: refreshed ? await refreshed.text() : "",
    };
  });

  expect(result.body).not.toContain("stale-cache-only-script");
  expect(result.body).toContain("screen-loading");
  expect(result.cachedBody).toBe(result.body);
});

test("a legacy Telegram shell refreshes once without stalling activation", async ({ page }) => {
  let navigationRequests = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      request.isNavigationRequest()
      && url.pathname === "/tests/browser-service-worker/harness.html"
    ) {
      navigationRequests += 1;
    }
  });

  await page.goto(
    "/tests/browser-service-worker/harness.html#tgWebAppData=retained-test-launch",
  );
  await page.evaluate(async () => {
    const legacy = await caches.open("quiz-miniapp-shell-v8.7.1-ui2");
    await legacy.put("/index.js", new Response("legacy", { status: 200 }));
    void navigator.serviceWorker.register(
      "/service-worker.js?upgrade-recovery=8.7.8-ui1",
      { scope: "/", updateViaCache: "none" },
    );
  });

  await expect.poll(() => navigationRequests).toBe(2);
  await expect.poll(async () => page.evaluate(() => ({
    controlled: Boolean(navigator.serviceWorker.controller),
    initData: window.harnessInitData,
  }))).toEqual({
    controlled: true,
    initData: "retained-test-launch",
  });
  await page.waitForTimeout(500);
  expect(navigationRequests).toBe(2);

  const cacheNames = await page.evaluate(() => caches.keys());
  expect(cacheNames).toContain(ACTIVE_SHELL_CACHE);
  expect(cacheNames).not.toContain("quiz-miniapp-shell-v8.7.1-ui2");
});

test("activation removes old service-worker cache versions", async ({ page }) => {
  await openHarness(page);
  const oldCaches = [
    "quiz-miniapp-shell-v0.0.1-old",
    "quiz-answer-free-v0.0.1-old",
  ];
  await page.evaluate(async (names) => {
    for (const name of names) {
      const cache = await caches.open(name);
      await cache.put(
        "/tests/browser-service-worker/legacy-entry",
        new Response("legacy", { status: 200 }),
      );
    }
  }, oldCaches);

  await registerAndControl(page);

  const cacheNames = await page.evaluate(() => caches.keys());
  expect(cacheNames).toContain(ACTIVE_SHELL_CACHE);
  for (const oldCache of oldCaches) {
    expect(cacheNames).not.toContain(oldCache);
  }
});
