const { test, expect } = require("@playwright/test");

async function loadTransport(page) {
  await page.goto("/privacy.html");
  await page.addScriptTag({ url: "/miniapp-shell.js" });
}

test("shared transport exposes the typed JSON and Response contracts", async ({ page }) => {
  await loadTransport(page);

  const contract = await page.evaluate(() => ({
    request: typeof window.miniappRequest,
    fetch: typeof window.miniappFetch,
    message: typeof window.miniappErrorMessage,
    errorType: typeof window.MiniAppRequestError,
    categories: { ...window.miniappErrorCategories },
    frozen: Object.isFrozen(window.miniappErrorCategories),
  }));

  expect(contract.request).toBe("function");
  expect(contract.fetch).toBe("function");
  expect(contract.message).toBe("function");
  expect(contract.errorType).toBe("function");
  expect(contract.frozen).toBe(true);
  expect(contract.categories).toMatchObject({
    OFFLINE: "OFFLINE",
    NETWORK_FAILURE: "NETWORK_FAILURE",
    REQUEST_TIMEOUT: "REQUEST_TIMEOUT",
    REQUEST_CANCELLED: "REQUEST_CANCELLED",
    SERVER_TEMPORARY: "SERVER_TEMPORARY",
    RATE_LIMITED: "RATE_LIMITED",
  });
});

test("shared shell synchronizes Telegram safe areas and stable viewport variables", async ({ page }) => {
  await page.goto("/privacy.html");
  await page.evaluate(() => {
    const handlers = {};
    window.__layoutHandlers = handlers;
    window.Telegram = {
      WebApp: {
        safeAreaInset: { top: 7, right: 2, bottom: 11, left: 3 },
        contentSafeAreaInset: { top: 9, right: 4, bottom: 34, left: 5 },
        viewportHeight: 640,
        viewportStableHeight: 620,
        onEvent(name, handler) { handlers[name] = handler; },
      },
    };
  });
  await page.addScriptTag({ url: "/miniapp-shell.js" });

  let variables = await page.evaluate(() => ({
    bottom: document.documentElement.style.getPropertyValue("--tg-content-safe-area-inset-bottom"),
    height: document.documentElement.style.getPropertyValue("--miniapp-viewport-height"),
    stable: document.documentElement.style.getPropertyValue("--miniapp-viewport-stable-height"),
    events: Object.keys(window.__layoutHandlers).sort(),
  }));
  expect(variables).toEqual({
    bottom: "34px",
    height: "640px",
    stable: "620px",
    events: ["contentSafeAreaChanged", "safeAreaChanged", "themeChanged", "viewportChanged"],
  });

  await page.evaluate(() => {
    window.Telegram.WebApp.contentSafeAreaInset.bottom = 48;
    window.Telegram.WebApp.viewportStableHeight = 600;
    window.__layoutHandlers.contentSafeAreaChanged();
  });
  variables = await page.evaluate(() => ({
    bottom: document.documentElement.style.getPropertyValue("--tg-content-safe-area-inset-bottom"),
    stable: document.documentElement.style.getPropertyValue("--miniapp-viewport-stable-height"),
  }));
  expect(variables).toEqual({ bottom: "48px", stable: "600px" });
});

test("safe GET retries one transient response and returns parsed JSON", async ({ page }) => {
  let calls = 0;
  await page.route("**/transport-test/transient", async (route) => {
    calls += 1;
    if (calls === 1) {
      await route.fulfill({ status: 503, body: "temporary private backend detail" });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, attempt: calls }),
    });
  });
  await loadTransport(page);

  const result = await page.evaluate(() => window.miniappRequest(
    "/transport-test/transient",
    { miniappRetryDelayMs: 0 },
  ));

  expect(result).toEqual({ ok: true, attempt: 2 });
  expect(calls).toBe(2);
});

test("rate limits are not retried and expose only typed safe metadata", async ({ page }) => {
  let calls = 0;
  const rawDetail = "SECRET rpc get_user_learning_dashboard_v2 failed";
  await page.route("**/transport-test/rate-limited", async (route) => {
    calls += 1;
    await route.fulfill({
      status: 429,
      contentType: "application/json",
      headers: { "Retry-After": "17", "X-Request-ID": "req-safe-429" },
      body: JSON.stringify({ detail: rawDetail }),
    });
  });
  await loadTransport(page);

  const result = await page.evaluate(async () => {
    try {
      await window.miniappRequest("/transport-test/rate-limited");
      return null;
    } catch (error) {
      return {
        name: error.name,
        category: error.category,
        status: error.status,
        requestId: error.requestId,
        retryAfterSeconds: error.retryAfterSeconds,
        retryable: error.retryable,
        message: error.message,
        safeCopy: window.miniappErrorMessage(error),
        serialized: JSON.stringify(error),
      };
    }
  });

  expect(calls).toBe(1);
  expect(result).toMatchObject({
    name: "MiniAppRequestError",
    category: "RATE_LIMITED",
    status: 429,
    requestId: "req-safe-429",
    retryAfterSeconds: 17,
    retryable: false,
  });
  expect(result.safeCopy).toContain("১৭");
  expect(JSON.stringify(result)).not.toContain(rawDetail);
  expect(result.message).not.toMatch(/rpc|SECRET|fetch|signal|AbortError/i);
});

test("writes and non-retryable read statuses are never automatically replayed", async ({ page }) => {
  const calls = {
    write: 0,
    invalid: 0,
    auth: 0,
    expired: 0,
    forbidden: 0,
    missing: 0,
    conflict: 0,
    response: 0,
  };
  const statuses = {
    write: 503,
    invalid: 400,
    auth: 401,
    expired: 401,
    forbidden: 403,
    missing: 404,
    conflict: 409,
    response: 404,
  };
  for (const key of Object.keys(statuses)) {
    await page.route(`**/transport-test/${key}`, async (route) => {
      calls[key] += 1;
      await route.fulfill({ status: statuses[key], body: "private failure detail" });
    });
  }
  await loadTransport(page);

  const outcome = await page.evaluate(async () => {
    const requests = [
      ["write", { method: "POST", body: "{}" }],
      ["invalid", {}],
      ["auth", {}],
      ["expired", { headers: { "X-Telegram-Init-Data": "signed-init-data" } }],
      ["forbidden", {}],
      ["missing", {}],
      ["conflict", {}],
    ];
    const output = {};
    for (const [name, options] of requests) {
      try {
        await window.miniappRequest(`/transport-test/${name}`, options);
      } catch (error) {
        output[name] = error.category;
      }
    }
    const response = await window.miniappFetch("/transport-test/response");
    return {
      categories: output,
      responseStatus: response.status,
      isResponse: response instanceof Response,
    };
  });

  expect(calls).toEqual({
    write: 1,
    invalid: 1,
    auth: 1,
    expired: 1,
    forbidden: 1,
    missing: 1,
    conflict: 1,
    response: 1,
  });
  expect(outcome.categories).toEqual({
    write: "SERVER_TEMPORARY",
    invalid: "INVALID_REQUEST",
    auth: "AUTH_REQUIRED",
    expired: "AUTH_EXPIRED",
    forbidden: "AUTH_REQUIRED",
    missing: "NOT_FOUND",
    conflict: "CONFLICT",
  });
  expect(outcome.responseStatus).toBe(404);
  expect(outcome.isResponse).toBe(true);
});

test("only 502, 503, and 504 HTTP reads qualify for the bounded status retry", async ({ page }) => {
  const calls = { 500: 0, 502: 0, 504: 0 };
  for (const status of [500, 502, 504]) {
    await page.route(`**/transport-test/status-${status}`, async (route) => {
      calls[status] += 1;
      await route.fulfill({ status, body: "private infrastructure detail" });
    });
  }
  await loadTransport(page);

  const errors = await page.evaluate(async () => {
    const output = {};
    for (const status of [500, 502, 504]) {
      try {
        await window.miniappRequest(`/transport-test/status-${status}`, {
          miniappRetryDelayMs: 0,
        });
      } catch (error) {
        output[status] = {
          category: error.category,
          status: error.status,
          retryable: error.retryable,
          message: error.message,
        };
      }
    }
    return output;
  });

  expect(calls).toEqual({ 500: 1, 502: 2, 504: 2 });
  for (const status of [500, 502, 504]) {
    expect(errors[status]).toMatchObject({
      category: "SERVER_TEMPORARY",
      status,
      retryable: status !== 500,
    });
    expect(errors[status].message).not.toMatch(/private|infrastructure|fetch|signal/i);
  }
});

test("network failures and timeouts get only one shorter retry", async ({ page }) => {
  await loadTransport(page);

  const result = await page.evaluate(async () => {
    const originalFetch = window.fetch;
    let networkCalls = 0;
    let timeoutCalls = 0;
    try {
      window.fetch = function (resource, options) {
        const url = String(resource);
        if (url.includes("network-retry")) {
          networkCalls += 1;
          if (networkCalls === 1) return Promise.reject(new TypeError("SECRET network detail"));
          return Promise.resolve(new Response('{"ok":true}', {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }));
        }
        if (url.includes("timeout")) {
          timeoutCalls += 1;
          return new Promise((resolve, reject) => {
            options.signal.addEventListener("abort", () => {
              reject(new DOMException("SECRET abort detail", "AbortError"));
            }, { once: true });
          });
        }
        return originalFetch(resource, options);
      };

      const network = await window.miniappRequest("/transport-test/network-retry", {
        miniappRetryDelayMs: 0,
      });
      let timeout;
      try {
        await window.miniappRequest("/transport-test/timeout", {
          miniappTimeoutMs: 30,
          miniappRetryTimeoutMs: 10,
          miniappRetryDelayMs: 0,
        });
      } catch (error) {
        timeout = {
          category: error.category,
          message: error.message,
          retryable: error.retryable,
        };
      }
      return { network, networkCalls, timeout, timeoutCalls };
    } finally {
      window.fetch = originalFetch;
    }
  });

  expect(result.network).toEqual({ ok: true });
  expect(result.networkCalls).toBe(2);
  expect(result.timeoutCalls).toBe(2);
  expect(result.timeout).toMatchObject({ category: "REQUEST_TIMEOUT", retryable: true });
  expect(result.timeout.message).not.toMatch(/SECRET|abort|signal|fetch/i);
});

test("caller cancellation is distinct and is never retried", async ({ page }) => {
  await loadTransport(page);

  const result = await page.evaluate(async () => {
    const originalFetch = window.fetch;
    let calls = 0;
    try {
      window.fetch = function (resource, options) {
        calls += 1;
        return new Promise((resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("caller stopped it", "AbortError"));
          }, { once: true });
        });
      };
      const controller = new AbortController();
      window.setTimeout(() => controller.abort(), 10);
      try {
        await window.miniappRequest("/transport-test/cancel", {
          signal: controller.signal,
          miniappTimeoutMs: 200,
          miniappRetryDelayMs: 0,
        });
      } catch (error) {
        return { calls, category: error.category, message: error.message };
      }
      return null;
    } finally {
      window.fetch = originalFetch;
    }
  });

  expect(result).toMatchObject({ calls: 1, category: "REQUEST_CANCELLED" });
  expect(result.message).not.toMatch(/caller stopped|abort|signal|fetch/i);
});

test("offline failures are distinct from generic network failures", async ({ page }) => {
  await loadTransport(page);

  const result = await page.evaluate(async () => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    try {
      await window.miniappRequest("/transport-test/offline", { miniappRetryDelayMs: 0 });
      return null;
    } catch (error) {
      return {
        category: error.category,
        retryable: error.retryable,
        message: window.miniappErrorMessage(error),
      };
    }
  });

  expect(result).toMatchObject({ category: "OFFLINE", retryable: false });
  expect(result.message).toContain("ইন্টারনেট সংযোগ নেই");
  expect(result.message).not.toMatch(/fetch|signal|AbortError/i);
});
