"use strict";

const SHELL_CACHE = "quiz-miniapp-shell-v8.7.0-ui1";
const ANSWER_FREE_CACHE = "quiz-answer-free-v8.7.0-ui1";
const SHELL_NETWORK_TIMEOUT_MS = 30000;
const BASE_URL = new URL("./", self.location.href);
const BASE_PATH = BASE_URL.pathname;
const SHELL_URLS = [
  "./",
  "index.html",
  "practice.html",
  "practice.css",
  "practice.js",
  "dashboard.html",
  "dashboard.css",
  "dashboard.js",
  "settings.html",
  "settings.css",
  "settings.js",
  "legal.css",
  "mock.html",
  "mock.css",
  "mock.js",
  "syllabus.html",
  "syllabus.css",
  "syllabus.js",
  "index.css",
  "index.js",
  "miniapp-shell.css",
  "miniapp-shell.js",
  "manifest.webmanifest",
  "pwa-icon.svg",
].map((path) => new URL(path, BASE_URL).pathname);

function appRelativePath(url) {
  if (!url.pathname.startsWith(BASE_PATH)) return null;
  return "/" + url.pathname.slice(BASE_PATH.length);
}

function isAnswerFreeProjection(url) {
  var path = appRelativePath(url);
  return path !== null && (
    path === "/api/quizzes/recent"
    || path === "/api/previous-year"
    || path === "/api/syllabus"
    || /^\/api\/quiz\/[^/]+$/.test(path)
    || /^\/api\/tests\/instances\/[0-9a-f-]+$/i.test(path)
  );
}

function isSensitiveApi(url) {
  var path = appRelativePath(url);
  return path !== null && path.startsWith("/api/") && !isAnswerFreeProjection(url);
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => ![SHELL_CACHE, ANSWER_FREE_CACHE].includes(key))
        .map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

async function answerFreeNetworkFirst(request) {
  var cache = await caches.open(ANSWER_FREE_CACHE);
  try {
    // The page transport owns API cancellation. A second service-worker
    // deadline can win the race during a cold start and surface a false
    // network failure even though the upstream request is still healthy.
    var response = await fetch(request, {cache: "no-store"});
    if (response.ok && response.headers.get("X-Answer-Free-Payload") === "1") {
      await cache.put(request, response.clone());
    }
    if (!response.ok && response.status >= 500) {
      var stale = await cache.match(request);
      if (stale) return stale;
    }
    return response;
  } catch (error) {
    var cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

function fetchWithTimeout(request, options, timeoutMs) {
  var controller = new AbortController();
  var timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(request, {...options, signal: controller.signal})
    .finally(() => clearTimeout(timer));
}

async function shellFromCacheOrNetwork(request) {
  var cache = await caches.open(SHELL_CACHE);
  var pathname = new URL(request.url).pathname;
  var cached = await cache.match(pathname);
  return cached || fetchWithTimeout(request, {cache: "no-store"}, SHELL_NETWORK_TIMEOUT_MS);
}

self.addEventListener("fetch", (event) => {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isSensitiveApi(url)) {
    // Sensitive learner/auth/answer requests are deliberately not intercepted.
    // The page transport owns their deadline, cancellation, classification,
    // and retry policy, and no service-worker cache ever sees their response.
    return;
  }
  if (isAnswerFreeProjection(url)) {
    event.respondWith(answerFreeNetworkFirst(request));
    return;
  }
  if (SHELL_URLS.includes(url.pathname)) {
    event.respondWith(shellFromCacheOrNetwork(request));
  }
});
