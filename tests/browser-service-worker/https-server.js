"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const https = require("node:https");
const os = require("node:os");
const path = require("node:path");

const HOST = "127.0.0.1";
const PORT = 4443;
const REPOSITORY_ROOT = path.resolve(__dirname, "../..");
const certificateDirectory = fs.mkdtempSync(
  path.join(os.tmpdir(), "citizen-affairs-sw-https-"),
);
const certificatePath = path.join(certificateDirectory, "localhost.crt");
const keyPath = path.join(certificateDirectory, "localhost.key");

// The certificate and key are ephemeral, test-only material. Nothing is checked in
// or reused outside this local HTTPS process.
execFileSync(
  "openssl",
  [
    "req",
    "-x509",
    "-newkey",
    "rsa:2048",
    "-nodes",
    "-keyout",
    keyPath,
    "-out",
    certificatePath,
    "-days",
    "1",
    "-subj",
    "/CN=127.0.0.1",
    "-addext",
    "subjectAltName=IP:127.0.0.1,DNS:localhost",
  ],
  { stdio: "ignore" },
);

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".webmanifest", "application/manifest+json; charset=utf-8"],
]);
const requestCounts = new Map();

function sendJson(response, status, payload, headers = {}) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    ...headers,
  });
  response.end(body);
}

function incrementRequestCount(url) {
  const key = url.pathname + url.search;
  const count = (requestCounts.get(key) || 0) + 1;
  requestCounts.set(key, count);
  return count;
}

async function serveApi(request, response, url) {
  const requestCount = incrementRequestCount(url);
  const probe = url.searchParams.get("probe") || "missing-probe";

  if (url.pathname === "/api/me/dashboard") {
    const requestedDelay = Number(url.searchParams.get("delayFirstMs") || 0);
    const delayFirstMs = Number.isFinite(requestedDelay)
      ? Math.max(0, Math.min(requestedDelay, 12_000))
      : 0;
    if (requestCount === 1 && delayFirstMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayFirstMs));
    }
    sendJson(response, 200, {
      kind: "sensitive-network-response",
      probe,
      requestCount,
    });
    return;
  }

  if (/^\/api\/quiz\/[^/]+$/.test(url.pathname)) {
    const requestedDelay = Number(url.searchParams.get("delayFirstMs") || 0);
    const delayFirstMs = Number.isFinite(requestedDelay)
      ? Math.max(0, Math.min(requestedDelay, 26_000))
      : 0;
    if (requestCount === 1 && delayFirstMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayFirstMs));
    }
    const failAfter = Number(url.searchParams.get("failAfter") || 0);
    if (failAfter > 0 && requestCount > failAfter) {
      sendJson(response, 503, {
        kind: "deliberate-upstream-failure",
        probe,
        requestCount,
      });
      return;
    }
    const headers = url.searchParams.get("answerFree") === "1"
      ? { "X-Answer-Free-Payload": "1" }
      : {};
    sendJson(response, 200, {
      kind: "answer-free-network-response",
      marker: `${probe}-${requestCount}`,
      probe,
      requestCount,
    }, headers);
    return;
  }

  sendJson(response, 404, { detail: "Test endpoint not found" });
}

function resolveStaticPath(url) {
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch (_error) {
    return null;
  }
  const relativePath = pathname === "/" ? "index.html" : pathname.slice(1);
  const candidate = path.resolve(REPOSITORY_ROOT, relativePath);
  if (
    candidate !== REPOSITORY_ROOT
    && !candidate.startsWith(REPOSITORY_ROOT + path.sep)
  ) {
    return null;
  }
  return candidate;
}

function serveStatic(request, response, url) {
  const filePath = resolveStaticPath(url);
  if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
    return;
  }

  const headers = {
    "Cache-Control": "no-store",
    "Content-Type": contentTypes.get(path.extname(filePath)) || "application/octet-stream",
  };
  if (url.pathname === "/service-worker.js") {
    headers["Service-Worker-Allowed"] = "/";
  }
  const body = fs.readFileSync(filePath);
  headers["Content-Length"] = body.length;
  response.writeHead(200, headers);
  response.end(request.method === "HEAD" ? undefined : body);
}

const server = https.createServer(
  {
    cert: fs.readFileSync(certificatePath),
    key: fs.readFileSync(keyPath),
  },
  (request, response) => {
    const url = new URL(request.url, `https://${HOST}:${PORT}`);
    if (url.pathname.startsWith("/api/")) {
      void serveApi(request, response, url);
      return;
    }
    serveStatic(request, response, url);
  },
);

function shutdown() {
  server.close(() => {
    fs.rmSync(certificateDirectory, { force: true, recursive: true });
    process.exit(0);
  });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
server.listen(PORT, HOST, () => {
  process.stdout.write(`HTTPS service-worker harness listening on https://${HOST}:${PORT}\n`);
});
