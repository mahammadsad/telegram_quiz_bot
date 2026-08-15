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
    navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(function () {
      // The Mini App remains fully usable online if registration is unavailable.
    });
  }

  function registerAdsense() {
    if (document.querySelector('script[data-adsense-client="ca-pub-4140283253043615"]')) return;
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4140283253043615";
    script.crossOrigin = "anonymous";
    script.setAttribute("data-adsense-client", "ca-pub-4140283253043615");
    document.head.appendChild(script);
  }

  function ready() {
    installSkipLink();
    announceNetworkState();
    registerWorker();
    registerAdsense();
    window.addEventListener("online", announceNetworkState);
    window.addEventListener("offline", announceNetworkState);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  window.__miniAppContract = Object.freeze({
    locale: "bn",
    supportedLocales: supportedLocales,
    shellVersion: "8.5.0-ui1",
  });
})();
