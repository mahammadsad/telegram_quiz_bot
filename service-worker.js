"use strict";

const SHELL_CACHE = "quiz-miniapp-shell-v8.4.0";
const ANSWER_FREE_CACHE = "quiz-answer-free-v8.4.0";
const SHELL_URLS = [
  "/",
  "/index.html",
  "/practice.html",
  "/dashboard.html",
  "/settings.html",
  "/mock.html",
  "/miniapp-shell.css",
  "/miniapp-shell.js",
  "/manifest.webmanifest",
  "/pwa-icon.svg",
];

function isAnswerFreeProjection(url) {
  return /^\/api\/quiz\/[^/]+$/.test(url.pathname)
    || /^\/api\/tests\/instances\/[0-9a-f-]+$/i.test(url.pathname);
}

function isSensitiveApi(url) {
  return url.pathname.startsWith("/api/") && !isAnswerFreeProjection(url);
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
    var response = await fetch(request, {cache: "no-store"});
    if (response.ok && response.headers.get("X-Answer-Free-Payload") === "1") {
      await cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    var cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isSensitiveApi(url)) {
    event.respondWith(fetch(request, {cache: "no-store"}));
    return;
  }
  if (isAnswerFreeProjection(url)) {
    event.respondWith(answerFreeNetworkFirst(request));
    return;
  }
  if (SHELL_URLS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});
