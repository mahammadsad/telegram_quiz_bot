(function () {
  "use strict";

  var supportedLocales = Object.freeze(["bn"]);
  var ERROR_CATEGORIES = Object.freeze({
    AUTH_REQUIRED: "AUTH_REQUIRED",
    AUTH_EXPIRED: "AUTH_EXPIRED",
    OFFLINE: "OFFLINE",
    NETWORK_FAILURE: "NETWORK_FAILURE",
    REQUEST_TIMEOUT: "REQUEST_TIMEOUT",
    REQUEST_CANCELLED: "REQUEST_CANCELLED",
    SERVER_TEMPORARY: "SERVER_TEMPORARY",
    RATE_LIMITED: "RATE_LIMITED",
    NOT_FOUND: "NOT_FOUND",
    INVALID_REQUEST: "INVALID_REQUEST",
    CONFLICT: "CONFLICT",
    UNKNOWN: "UNKNOWN",
  });
  var ERROR_MESSAGES = Object.freeze({
    AUTH_REQUIRED: "Telegram থেকে Mini App খুলে আবার চেষ্টা করুন।",
    AUTH_EXPIRED: "Telegram যাচাইয়ের সময় শেষ হয়েছে। Mini App আবার খুলুন।",
    OFFLINE: "ইন্টারনেট সংযোগ নেই। সংযোগ ফিরলে আবার চেষ্টা করুন।",
    NETWORK_FAILURE: "সার্ভারের সঙ্গে সংযোগ করা যায়নি। একটু পরে আবার চেষ্টা করুন।",
    REQUEST_TIMEOUT: "সাড়া পেতে বেশি সময় লাগছে। আবার চেষ্টা করুন।",
    REQUEST_CANCELLED: "অনুরোধটি বাতিল হয়েছে।",
    SERVER_TEMPORARY: "সেবা সাময়িকভাবে ব্যস্ত। একটু পরে আবার চেষ্টা করুন।",
    RATE_LIMITED: "খুব দ্রুত অনুরোধ করা হয়েছে। একটু পরে আবার চেষ্টা করুন।",
    NOT_FOUND: "অনুরোধ করা তথ্যটি পাওয়া যায়নি।",
    INVALID_REQUEST: "অনুরোধটি সম্পন্ন করা যায়নি। তথ্য যাচাই করে আবার চেষ্টা করুন।",
    CONFLICT: "তথ্যটি ইতিমধ্যে বদলেছে। পাতা হালনাগাদ করে আবার চেষ্টা করুন।",
    UNKNOWN: "অনুরোধটি সম্পন্ন করা যায়নি। একটু পরে আবার চেষ্টা করুন।",
  });
  var FIRST_GET_TIMEOUT_MS = 30000;
  var WRITE_TIMEOUT_MS = 30000;
  var SECOND_GET_TIMEOUT_MS = 12000;
  var RETRY_JITTER_MIN_MS = 150;
  var RETRY_JITTER_MAX_MS = 350;
  var SAFE_RETRY_STATUSES = Object.freeze([502, 503, 504]);
  document.documentElement.lang = supportedLocales[0];

  function safeRequestId(value) {
    var candidate = typeof value === "string" ? value.trim() : "";
    return /^[A-Za-z0-9._:-]{1,128}$/.test(candidate) ? candidate : null;
  }

  function miniappErrorMessage(error) {
    var category = error && ERROR_MESSAGES[error.category]
      ? error.category
      : ERROR_CATEGORIES.UNKNOWN;
    var message = ERROR_MESSAGES[category];
    var retryAfter = error && Number(error.retryAfterSeconds);
    if (category === ERROR_CATEGORIES.RATE_LIMITED && Number.isFinite(retryAfter) && retryAfter > 0) {
      var localizedSeconds = String(Math.ceil(retryAfter)).replace(/[0-9]/g, function (digit) {
        return "০১২৩৪৫৬৭৮৯"[Number(digit)];
      });
      message = "আরও " + localizedSeconds + " সেকেন্ড পরে আবার চেষ্টা করুন।";
    }
    var requestId = safeRequestId(error && error.requestId);
    if (requestId && (
      category === ERROR_CATEGORIES.SERVER_TEMPORARY
      || category === ERROR_CATEGORIES.UNKNOWN
    )) {
      message += " রেফারেন্স: " + requestId;
    }
    return message;
  }

  function MiniAppRequestError(category, details) {
    var safeCategory = ERROR_MESSAGES[category] ? category : ERROR_CATEGORIES.UNKNOWN;
    var metadata = details || {};
    this.name = "MiniAppRequestError";
    this.category = safeCategory;
    this.status = Number.isInteger(metadata.status) ? metadata.status : null;
    this.requestId = safeRequestId(metadata.requestId);
    this.retryAfterSeconds = Number.isFinite(metadata.retryAfterSeconds)
      ? Math.max(0, metadata.retryAfterSeconds)
      : null;
    this.retryable = Boolean(metadata.retryable);
    this.message = miniappErrorMessage(this);
    if (Error.captureStackTrace) Error.captureStackTrace(this, MiniAppRequestError);
  }
  MiniAppRequestError.prototype = Object.create(Error.prototype);
  MiniAppRequestError.prototype.constructor = MiniAppRequestError;

  function announceNetworkState() {
    var banner = document.getElementById("network-status");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "network-status";
      banner.className = "network-status";
      banner.setAttribute("role", "status");
      banner.setAttribute("aria-live", "polite");
      banner.setAttribute("aria-atomic", "true");
      document.body.insertBefore(banner, document.body.firstChild);
    }
    var offline = navigator.onLine === false;
    banner.hidden = !offline;
    banner.textContent = offline
      ? "ইন্টারনেট নেই—আপনার খসড়া এই ডিভাইসে নিরাপদ আছে। সংযোগ ফিরলে আবার চেষ্টা করুন।"
      : "";
    document.documentElement.classList.toggle("is-offline", offline);
    window.dispatchEvent(new CustomEvent("miniapp:network", {detail: {online: !offline}}));
  }

  function installSkipLink() {
    var main = document.querySelector("main");
    if (!main || document.querySelector(".skip-link")) return;
    if (!main.id) main.id = "main-content";
    main.setAttribute("tabindex", "-1");
    var link = document.createElement("a");
    link.className = "skip-link";
    link.href = "#" + main.id;
    link.textContent = "মূল অংশে যান";
    document.body.insertBefore(link, document.body.firstChild);
  }

  function registerWorker() {
    if (!("serviceWorker" in navigator) || location.protocol !== "https:") return;
    var workerUrl = new URL("service-worker.js", document.baseURI);
    workerUrl.searchParams.set("shell", "8.7.2-ui3");
    var workerScope = new URL("./", workerUrl).pathname;
    navigator.serviceWorker.register(workerUrl.href, {
      scope: workerScope,
      updateViaCache: "none",
    }).then(function (registration) {
      // Do not wait for the browser's periodic update interval. Telegram
      // WebViews may otherwise keep an old cache-first worker for many hours.
      return registration.update();
    }).catch(function () {
      // The Mini App remains fully usable online if registration is unavailable.
    });
  }

  function statusCategory(status, authPresented) {
    if (status === 400 || status === 422) return ERROR_CATEGORIES.INVALID_REQUEST;
    if (status === 401 || status === 403) {
      return authPresented ? ERROR_CATEGORIES.AUTH_EXPIRED : ERROR_CATEGORIES.AUTH_REQUIRED;
    }
    if (status === 404) return ERROR_CATEGORIES.NOT_FOUND;
    if (status === 408) return ERROR_CATEGORIES.REQUEST_TIMEOUT;
    if (status === 409) return ERROR_CATEGORIES.CONFLICT;
    if (status === 429) return ERROR_CATEGORIES.RATE_LIMITED;
    if (status >= 500) return ERROR_CATEGORIES.SERVER_TEMPORARY;
    return ERROR_CATEGORIES.UNKNOWN;
  }

  function requestIdFrom(response) {
    if (!response || !response.headers) return null;
    return safeRequestId(
      response.headers.get("X-Request-ID")
      || response.headers.get("X-Correlation-ID"),
    );
  }

  function retryAfterSecondsFrom(response) {
    if (!response || !response.headers) return null;
    var value = response.headers.get("Retry-After");
    if (!value) return null;
    var seconds = Number(value);
    if (Number.isFinite(seconds)) return Math.max(0, seconds);
    var date = Date.parse(value);
    if (!Number.isFinite(date)) return null;
    return Math.max(0, Math.ceil((date - Date.now()) / 1000));
  }

  function isSafeRetryStatus(status) {
    return SAFE_RETRY_STATUSES.indexOf(status) !== -1;
  }

  function isRetryableError(error) {
    return Boolean(error && (
      error.category === ERROR_CATEGORIES.NETWORK_FAILURE
      || error.category === ERROR_CATEGORIES.REQUEST_TIMEOUT
    ));
  }

  function typedError(category, details) {
    if (details && details.status !== null && details.status !== undefined) {
      details.retryable = isSafeRetryStatus(details.status);
    } else if (details) {
      details.retryable = category === ERROR_CATEGORIES.NETWORK_FAILURE
        || category === ERROR_CATEGORIES.REQUEST_TIMEOUT;
    }
    return new MiniAppRequestError(category, details);
  }

  function cleanTransportOptions(options) {
    var cleaned = Object.assign({}, options || {});
    delete cleaned.miniappTimeoutMs;
    delete cleaned.miniappRetryTimeoutMs;
    delete cleaned.miniappRetryDelayMs;
    delete cleaned.miniappRetry;
    return cleaned;
  }

  function headerValue(headers, name) {
    if (!headers) return null;
    if (typeof headers.get === "function") return headers.get(name);
    if (Array.isArray(headers)) {
      var pair = headers.find(function (item) {
        return Array.isArray(item) && String(item[0]).toLowerCase() === name.toLowerCase();
      });
      return pair ? pair[1] : null;
    }
    var key = Object.keys(headers).find(function (candidate) {
      return candidate.toLowerCase() === name.toLowerCase();
    });
    return key ? headers[key] : null;
  }

  function hasTelegramAuth(resource, options) {
    var supplied = options || {};
    var header = headerValue(supplied.headers, "X-Telegram-Init-Data")
      || headerValue(resource && resource.headers, "X-Telegram-Init-Data");
    if (typeof header === "string" && header.length > 0) return true;
    if (typeof supplied.body !== "string" || supplied.body.length > 100000) return false;
    try {
      var payload = JSON.parse(supplied.body);
      return Boolean(payload && typeof payload.initData === "string" && payload.initData.length > 0);
    } catch (_) {
      return false;
    }
  }

  function transportSettings(resource, options, timeoutMs) {
    var supplied = options || {};
    var resourceMethod = resource && typeof resource.method === "string" ? resource.method : "GET";
    var method = String(supplied.method || resourceMethod || "GET").toUpperCase();
    var configuredTimeout = typeof timeoutMs === "number" ? timeoutMs : supplied.miniappTimeoutMs;
    var firstTimeout = Number.isFinite(configuredTimeout) && configuredTimeout > 0
      ? configuredTimeout
      : (method === "GET" ? FIRST_GET_TIMEOUT_MS : WRITE_TIMEOUT_MS);
    var configuredSecond = supplied.miniappRetryTimeoutMs;
    var secondTimeout = Number.isFinite(configuredSecond) && configuredSecond > 0
      ? Math.min(configuredSecond, firstTimeout)
      : Math.min(SECOND_GET_TIMEOUT_MS, Math.max(1, Math.floor(firstTimeout / 2)));
    var configuredDelay = supplied.miniappRetryDelayMs;
    var retryDelay = Number.isFinite(configuredDelay) && configuredDelay >= 0
      ? Math.min(RETRY_JITTER_MAX_MS, configuredDelay)
      : RETRY_JITTER_MIN_MS + Math.floor(
        Math.random() * (RETRY_JITTER_MAX_MS - RETRY_JITTER_MIN_MS + 1),
      );
    return {
      method: method,
      firstTimeout: firstTimeout,
      secondTimeout: secondTimeout,
      retryDelay: retryDelay,
      retryAllowed: method === "GET" && supplied.miniappRetry !== false,
      callerSignal: supplied.signal || (resource && resource.signal) || null,
      fetchOptions: cleanTransportOptions(supplied),
    };
  }

  function fetchAttempt(resource, fetchOptions, callerSignal, timeoutMs) {
    if (callerSignal && callerSignal.aborted) {
      return Promise.reject(typedError(ERROR_CATEGORIES.REQUEST_CANCELLED, {}));
    }
    if (navigator.onLine === false) {
      return Promise.reject(typedError(ERROR_CATEGORIES.OFFLINE, {retryable: false}));
    }
    if (typeof window.AbortController !== "function") {
      return window.fetch(resource, fetchOptions).catch(function () {
        if (callerSignal && callerSignal.aborted) {
          throw typedError(ERROR_CATEGORIES.REQUEST_CANCELLED, {});
        }
        var category = navigator.onLine === false
          ? ERROR_CATEGORIES.OFFLINE
          : ERROR_CATEGORIES.NETWORK_FAILURE;
        throw typedError(category, {});
      });
    }

    var controller = new window.AbortController();
    var requestOptions = Object.assign({}, fetchOptions, {signal: controller.signal});
    var timedOut = false;
    var cancelledByCaller = false;
    var onCallerAbort = function () {
      cancelledByCaller = true;
      controller.abort();
    };
    if (callerSignal) callerSignal.addEventListener("abort", onCallerAbort, {once: true});
    var timer = window.setTimeout(function () {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    return Promise.resolve().then(function () {
      return window.fetch(resource, requestOptions);
    }).catch(function () {
      if (cancelledByCaller || (callerSignal && callerSignal.aborted)) {
        throw typedError(ERROR_CATEGORIES.REQUEST_CANCELLED, {});
      }
      if (timedOut) throw typedError(ERROR_CATEGORIES.REQUEST_TIMEOUT, {});
      if (navigator.onLine === false) throw typedError(ERROR_CATEGORIES.OFFLINE, {});
      throw typedError(ERROR_CATEGORIES.NETWORK_FAILURE, {});
    }).finally(function () {
      window.clearTimeout(timer);
      if (callerSignal) callerSignal.removeEventListener("abort", onCallerAbort);
    });
  }

  function waitForRetry(delayMs, callerSignal) {
    if (callerSignal && callerSignal.aborted) {
      return Promise.reject(typedError(ERROR_CATEGORIES.REQUEST_CANCELLED, {}));
    }
    return new Promise(function (resolve, reject) {
      var timer;
      var onAbort = function () {
        window.clearTimeout(timer);
        callerSignal.removeEventListener("abort", onAbort);
        reject(typedError(ERROR_CATEGORIES.REQUEST_CANCELLED, {}));
      };
      if (callerSignal) callerSignal.addEventListener("abort", onAbort, {once: true});
      timer = window.setTimeout(function () {
        if (callerSignal) callerSignal.removeEventListener("abort", onAbort);
        resolve();
      }, delayMs);
    });
  }

  function announceRetry(reason, status) {
    window.dispatchEvent(new CustomEvent("miniapp:request-retry", {
      detail: {attempt: 2, category: reason || null, status: status || null},
    }));
  }

  function fetchWithPolicy(resource, options, timeoutMs) {
    var settings = transportSettings(resource, options, timeoutMs);
    return fetchAttempt(
      resource,
      settings.fetchOptions,
      settings.callerSignal,
      settings.firstTimeout,
    ).then(
      function (response) {
        if (!settings.retryAllowed || !isSafeRetryStatus(response.status)) return response;
        if (response.body && typeof response.body.cancel === "function") {
          response.body.cancel().catch(function () {});
        }
        announceRetry(statusCategory(response.status), response.status);
        return waitForRetry(settings.retryDelay, settings.callerSignal).then(function () {
          return fetchAttempt(
            resource,
            settings.fetchOptions,
            settings.callerSignal,
            settings.secondTimeout,
          );
        });
      },
      function (error) {
        if (!settings.retryAllowed || !isRetryableError(error)) throw error;
        announceRetry(error.category, null);
        return waitForRetry(settings.retryDelay, settings.callerSignal).then(function () {
          return fetchAttempt(
            resource,
            settings.fetchOptions,
            settings.callerSignal,
            settings.secondTimeout,
          );
        });
      },
    );
  }

  function responseError(response, authPresented) {
    return typedError(statusCategory(response.status, authPresented), {
      status: response.status,
      requestId: requestIdFrom(response),
      retryAfterSeconds: retryAfterSecondsFrom(response),
    });
  }

  function miniappRequest(resource, options) {
    var authPresented = hasTelegramAuth(resource, options);
    return fetchWithPolicy(resource, options).then(function (response) {
      if (!response.ok) throw responseError(response, authPresented);
      if (response.status === 204 || response.status === 205) return null;
      return response.text().then(function (body) {
        if (!body) return null;
        try {
          return JSON.parse(body);
        } catch (_) {
          throw typedError(ERROR_CATEGORIES.UNKNOWN, {
            status: response.status,
            requestId: requestIdFrom(response),
          });
        }
      });
    });
  }

  function cssPixels(value, fallback) {
    var number = Number(value);
    if (!Number.isFinite(number) || number < 0) number = Number(fallback) || 0;
    return Math.min(number, 10000).toFixed(2).replace(/\.00$/, "") + "px";
  }

  function insetValue(source, edge) {
    return source && Number.isFinite(Number(source[edge])) ? Number(source[edge]) : 0;
  }

  function syncTelegramLayout() {
    var rootStyle = document.documentElement.style;
    var webApp = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    var safeArea = webApp && webApp.safeAreaInset ? webApp.safeAreaInset : {};
    var contentSafeArea = webApp && webApp.contentSafeAreaInset
      ? webApp.contentSafeAreaInset
      : {};
    ["top", "right", "bottom", "left"].forEach(function (edge) {
      rootStyle.setProperty("--tg-safe-area-inset-" + edge, cssPixels(insetValue(safeArea, edge)));
      rootStyle.setProperty(
        "--tg-content-safe-area-inset-" + edge,
        cssPixels(insetValue(contentSafeArea, edge)),
      );
    });
    var viewportHeight = webApp && Number(webApp.viewportHeight) > 0
      ? Number(webApp.viewportHeight)
      : window.innerHeight;
    var stableHeight = webApp && Number(webApp.viewportStableHeight) > 0
      ? Number(webApp.viewportStableHeight)
      : viewportHeight;
    rootStyle.setProperty("--tg-viewport-height", cssPixels(viewportHeight, window.innerHeight));
    rootStyle.setProperty("--tg-viewport-stable-height", cssPixels(stableHeight, viewportHeight));
    rootStyle.setProperty("--miniapp-viewport-height", cssPixels(viewportHeight, window.innerHeight));
    rootStyle.setProperty("--miniapp-viewport-stable-height", cssPixels(stableHeight, viewportHeight));
    window.dispatchEvent(new CustomEvent("miniapp:layout", {
      detail: {viewportHeight: viewportHeight, viewportStableHeight: stableHeight},
    }));
  }

  function installTelegramLayoutSync() {
    syncTelegramLayout();
    var webApp = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (webApp && typeof webApp.onEvent === "function") {
      ["viewportChanged", "safeAreaChanged", "contentSafeAreaChanged", "themeChanged"]
        .forEach(function (eventName) {
          try { webApp.onEvent(eventName, syncTelegramLayout); } catch (_) {}
        });
    }
    window.addEventListener("resize", syncTelegramLayout, {passive: true});
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", syncTelegramLayout, {passive: true});
      window.visualViewport.addEventListener("scroll", syncTelegramLayout, {passive: true});
    }
  }

  function ready() {
    installSkipLink();
    announceNetworkState();
    installTelegramLayoutSync();
    registerWorker();
    window.addEventListener("online", announceNetworkState);
    window.addEventListener("offline", announceNetworkState);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  window.__miniAppContract = Object.freeze({
    locale: "bn",
    supportedLocales: supportedLocales,
    shellVersion: "8.7.2-ui3",
    basePath: new URL("./", document.baseURI).pathname,
    errorCategories: ERROR_CATEGORIES,
  });
  window.MiniAppRequestError = MiniAppRequestError;
  window.miniappErrorCategories = ERROR_CATEGORIES;
  window.miniappErrorMessage = miniappErrorMessage;
  window.miniappSyncLayout = syncTelegramLayout;
  // Response-compatible transport for existing pages. HTTP failures still
  // resolve to Response objects; only safe GETs receive one bounded retry.
  window.miniappFetch = fetchWithPolicy;
  // JSON transport for new and migrated callers. It never exposes server or
  // browser exception details as learner-facing copy.
  window.miniappRequest = miniappRequest;
})();
