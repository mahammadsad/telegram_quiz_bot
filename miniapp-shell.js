(function () {
  "use strict";

  var supportedLocales = Object.freeze(["bn"]);
  document.documentElement.lang = supportedLocales[0];

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
    var workerScope = new URL("./", workerUrl).pathname;
    navigator.serviceWorker.register(workerUrl.href, {scope: workerScope}).catch(function () {
      // The Mini App remains fully usable online if registration is unavailable.
    });
  }

  function fetchWithTimeout(resource, options, timeoutMs) {
    var requestOptions = Object.assign({}, options || {});
    if (typeof window.AbortController !== "function") return window.fetch(resource, requestOptions);
    var controller = new window.AbortController();
    var originalSignal = requestOptions.signal;
    requestOptions.signal = controller.signal;
    if (originalSignal) {
      if (originalSignal.aborted) controller.abort();
      else originalSignal.addEventListener("abort", function () { controller.abort(); }, {once: true});
    }
    var timeout = typeof timeoutMs === "number"
      ? timeoutMs
      : (String(requestOptions.method || "GET").toUpperCase() === "GET" ? 15000 : 30000);
    var timer = window.setTimeout(function () { controller.abort(); }, timeout);
    return window.fetch(resource, requestOptions).finally(function () { window.clearTimeout(timer); });
  }

  function ready() {
    installSkipLink();
    announceNetworkState();
    registerWorker();
    window.addEventListener("online", announceNetworkState);
    window.addEventListener("offline", announceNetworkState);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  window.__miniAppContract = Object.freeze({
    locale: "bn",
    supportedLocales: supportedLocales,
    shellVersion: "8.6.0-ui2",
    basePath: new URL("./", document.baseURI).pathname,
  });
  // All Mini App pages use this for bounded network waits. A stalled mobile
  // connection must show a retry state rather than leave the learner spinning.
  window.miniappFetch = fetchWithTimeout;
})();
