(function(){
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  var isTelegram = !!(tg && tg.initData);
  var telegramLaunchHash = /(?:^|&)tgWebAppData=/.test(window.location.hash.slice(1))
    ? window.location.hash
    : "";
  installTelegramNavigation();
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      document.body.classList.toggle("tg-native", isTelegram);
      if (isTelegram) {
        tg.enableClosingConfirmation();
        try { tg.setHeaderColor("#f5f7fb"); tg.setBackgroundColor("#f5f7fb"); } catch(e){}
      }
    } catch(e){}
  }

  var API_BASE = (window.QUIZ_API_BASE || document.querySelector('meta[name="quiz-api-base"]').content || "").replace(/\/$/, "");
  var BN = ["০","১","২","৩","৪","৫","৬","৭","৮","৯"];
  var LETTERS = ["A","B","C","D"];

  var quizId = getQuizId();
  prepareTelegramHandoffLinks();
  var requestedAttemptId = getResultAttemptId();
  var requestedHomeSubject = new URLSearchParams(location.search).get("subject") || "";
  var homeSubjects = ["history","geography","polity","economics","science","mathematics","reasoning","english","bengali","computer","current-affairs","environment","miscellaneous"];
  if (homeSubjects.indexOf(requestedHomeSubject) < 0) requestedHomeSubject = "";
  var quiz = null;
  var legacyLocal = false;
  var readOnlyMode = false;
  var answers = [];
  var current = 0;
  var totalSeconds = 0;
  var timeLeft = 0;
  var timerHandle = null;
  var screen = "loading";
  var submitting = false;
  var attemptId = "";
  var markedForReview = [];
  var responseTimes = [];
  var startedAt = 0;
  var questionStartedAt = 0;
  var quizMode = "timed";
  var serverAttemptStarted = false;
  var serverStartPromise = null;
  var retryAction = loadQuiz;

  var screens = {
    loading: byId("screen-loading"),
    home: byId("screen-home"),
    error: byId("screen-error"),
    intro: byId("screen-intro"),
    resources: byId("screen-resources"),
    quiz: byId("screen-quiz"),
    result: byId("screen-result")
  };

  byId("btn-start").addEventListener("click", startQuiz);
  byId("btn-prepare").addEventListener("click", loadResources);
  byId("btn-resource-back").addEventListener("click", function(){ show("intro"); });
  byId("btn-resource-start").addEventListener("click", startQuiz);
  byId("btn-fallback-retry").addEventListener("click", loadQuiz);
  byId("btn-preview").addEventListener("click", function(){ startQuiz(true); });
  byId("btn-prev").addEventListener("click", goPrev);
  byId("btn-next").addEventListener("click", nextOrFinish);
  byId("btn-retake").addEventListener("click", startQuiz);
  byId("btn-dashboard").addEventListener("click", openDashboard);
  byId("btn-personal-dashboard").addEventListener("click", function(){ navigateTelegram("dashboard.html"); });
  byId("btn-wrong-practice").addEventListener("click", openWrongPractice);
  byId("btn-revise").addEventListener("click", openRevisionPractice);
  byId("btn-mark").addEventListener("click", toggleMarked);
  byId("btn-resume").addEventListener("click", resumeDraft);
  byId("btn-new-attempt").addEventListener("click", function(){ discardDraft(); startQuiz(); });
  byId("btn-submit-back").addEventListener("click", hideSubmitConfirmation);
  byId("btn-submit-confirm").addEventListener("click", function(){ hideSubmitConfirmation(); finishQuiz(true); });
  byId("btn-retry").addEventListener("click", function(){ retryAction(); });
  byId("btn-home-retry").addEventListener("click", loadHome);

  if (isTelegram) {
    tg.MainButton.onClick(function(){
      if (screen === "intro") legacyLocal ? loadQuiz() : startQuiz();
      else if (screen === "resources") startQuiz();
      else if (screen === "quiz") nextOrFinish();
      else if (screen === "result") openDashboard();
    });
    tg.BackButton.onClick(function(){
      if (screen === "quiz") goPrev();
      else if (screen === "resources") show("intro");
      else if (screen === "result") show("intro");
    });
  }

  document.addEventListener("keydown", function(event){
    if (screen !== "quiz") return;
    if (["1","2","3","4"].indexOf(event.key) >= 0) {
      answers[current] = Number(event.key) - 1;
      saveDraft();
      renderQuestion();
    } else if (event.key === "ArrowLeft") goPrev();
    else if (event.key === "ArrowRight") nextOrFinish();
  });

  if (!quizId) {
    loadHome();
  } else {
    byId("quiz-id-pill").textContent = "#" + quizId;
    byId("nav-quiz").href = quizHomeUrl();
    loadQuizPreferences();
    loadQuiz();
  }

  function byId(id){ return document.getElementById(id); }
  function bn(value){ return String(value).replace(/[0-9]/g, function(d){ return BN[+d]; }); }
  function formatScore(value){
    var number = Number(value);
    if (!Number.isFinite(number)) number = 0;
    return (Math.round(number * 100) / 100).toFixed(2).replace(/\.?0+$/, "");
  }
  function markingScheme(){
    var marking = quiz && quiz.capabilities && quiz.capabilities.marking;
    return marking || {
      rightMarks:1,
      wrongPenalty:0,
      blankMarks:0,
      negativeMarking:false
    };
  }
  function pad2(n){ return n < 10 ? "0" + n : "" + n; }
  function api(path){ return API_BASE + path; }
  function telegramUrl(path){
    var url = new URL(path, window.location.href);
    if (url.origin !== window.location.origin) return url.href;
    if (telegramLaunchHash) {
      if (url.hash && url.hash !== telegramLaunchHash) {
        var section = url.hash.slice(1);
        if (/^[A-Za-z0-9_-]+$/.test(section)) url.searchParams.set("section", section);
      }
      url.hash = telegramLaunchHash;
    }
    return url.pathname + url.search + url.hash;
  }
  function navigateTelegram(path){ window.location.href = telegramUrl(path); }
  function installTelegramNavigation(){
    if (!telegramLaunchHash) return;
    document.addEventListener("click", function(event){
      if (event.defaultPrevented || (event.button !== undefined && event.button !== 0) ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var link = event.target.closest ? event.target.closest("a[href]") : null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      var url = new URL(link.getAttribute("href"), window.location.href);
      if (url.origin !== window.location.origin) return;
      event.preventDefault();
      navigateTelegram(link.getAttribute("href"));
    });
  }
  function quizHomeUrl(){ return telegramUrl("./?quiz=" + encodeURIComponent(quizId)); }
  function jsonOrThrow(resp, label){
    if (resp.ok) return resp.json();
    return resp.json().catch(function(){ return {}; }).then(function(body){
      var err = new Error(body.detail || (label + " returned " + resp.status));
      err.status = resp.status;
      throw err;
    });
  }

  function fetchWithTimeout(resource, options, timeoutMs){
    var controller = new AbortController();
    var requestOptions = Object.assign({}, options || {}, {signal:controller.signal});
    var timer = window.setTimeout(function(){ controller.abort(); }, timeoutMs || 8000);
    return window.fetch(resource, requestOptions).finally(function(){ window.clearTimeout(timer); });
  }

  function getQuizId(){
    var params = new URLSearchParams(window.location.search);
    if (isTelegram && tg.initDataUnsafe && tg.initDataUnsafe.start_param) return tg.initDataUnsafe.start_param;
    return params.get("quiz") || params.get("id") || params.get("startapp") || "";
  }

  function prepareTelegramHandoffLinks(){
    var configured = document.querySelector('meta[name="telegram-miniapp-url"]');
    var base = configured ? configured.content.trim() : "";
    if (!/^https:\/\/t\.me\/[A-Za-z0-9_]+\/[A-Za-z0-9_]+\/?$/.test(base)) return;
    var home = byId("telegram-home-launch");
    var direct = byId("telegram-quiz-launch");
    if (home) home.href = base;
    if (direct && quizId) {
      var url = new URL(base);
      url.searchParams.set("startapp", quizId);
      direct.href = url.href;
    }
  }

  function validAttemptId(value){
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value || "");
  }

  function getResultAttemptId(){
    var value = new URLSearchParams(window.location.search).get("attempt") || "";
    return validAttemptId(value) ? value.toLowerCase() : "";
  }

  function rememberResultLocation(value){
    if (!validAttemptId(value) || !window.history || !window.history.replaceState) return;
    requestedAttemptId = value.toLowerCase();
    var url = new URL(window.location.href);
    url.searchParams.set("quiz", quizId);
    url.searchParams.set("attempt", requestedAttemptId);
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }

  function clearResultLocation(){
    requestedAttemptId = "";
    if (!window.history || !window.history.replaceState) return;
    var url = new URL(window.location.href);
    url.searchParams.delete("attempt");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }

  function loadQuizPreferences(){
    if (!isTelegram) return;
    fetchWithTimeout(api("/api/me/preferences"), {headers:{"X-Telegram-Init-Data":tg.initData}})
      .then(function(resp){ return jsonOrThrow(resp, "Preferences API"); })
      .then(function(data){
        quizMode = data.quizMode === "practice" ? "practice" : "timed";
        if (quiz && !requestedAttemptId && screen === "intro") renderIntro();
      })
      .catch(function(){ quizMode = "timed"; });
  }

  function draftKey(){ return "telegram-quiz-draft:" + quizId; }
  function readDraft(){
    try {
      var draft = JSON.parse(localStorage.getItem(draftKey()) || "null");
      if (!draft || draft.quizId !== quizId || !Array.isArray(draft.answers) || draft.answers.length !== 10) return null;
      if (!draft.savedAt || Date.now() - draft.savedAt > 24 * 60 * 60 * 1000) { discardDraft(); return null; }
      return draft;
    } catch(e) { return null; }
  }
  function saveDraft(){
    if (!quiz || readOnlyMode || screen !== "quiz") return;
    try {
      localStorage.setItem(draftKey(), JSON.stringify({
        quizId:quizId, attemptId:attemptId, answers:answers, current:current,
        markedForReview:markedForReview, responseTimes:responseTimes,
        timeLeft:timeLeft, totalSeconds:totalSeconds, startedAt:startedAt,
        savedAt:Date.now(), quizMode:quizMode
      }));
    } catch(e) {}
  }
  function discardDraft(){ try { localStorage.removeItem(draftKey()); } catch(e) {} }
  function resumeDraft(){
    var draft = readDraft();
    if (!draft) { startQuiz(); return; }
    readOnlyMode = false;
    attemptId = draft.attemptId || newAttemptId();
    answers = draft.answers.map(function(value){ return value === null || [0,1,2,3].indexOf(value) >= 0 ? value : null; });
    markedForReview = Array.isArray(draft.markedForReview) && draft.markedForReview.length === 10 ? draft.markedForReview.map(Boolean) : quiz.qs.map(function(){ return false; });
    responseTimes = Array.isArray(draft.responseTimes) && draft.responseTimes.length === 10 ? draft.responseTimes : quiz.qs.map(function(){ return null; });
    current = Math.max(0, Math.min(9, Number(draft.current) || 0));
    totalSeconds = Number(draft.totalSeconds) || Math.max(300, quiz.qs.length * 60);
    var offline = Math.max(0, Math.floor((Date.now() - draft.savedAt) / 1000));
    timeLeft = quizMode === "practice" ? totalSeconds : Math.max(0, (Number(draft.timeLeft) || totalSeconds) - offline);
    startedAt = Number(draft.startedAt) || Date.now();
    ensureServerAttemptStarted().catch(function(){});
    questionStartedAt = Date.now();
    prepareQuizHeader();
    renderQuestion();
    startTimer();
    show("quiz");
  }

  function show(name){
    screen = name;
    Object.keys(screens).forEach(function(key){ screens[key].classList.toggle("hidden", key !== name); });
    syncTelegramButtons();
  }

  function syncTelegramButtons(){
    if (!isTelegram) return;
    if (screen === "intro") {
      tg.BackButton.hide();
      tg.MainButton.setParams({text:legacyLocal ? "লাইভ কুইজ আবার চেষ্টা করুন" : "মক টেস্ট শুরু করুন", is_visible:true, color:"#0f766e", text_color:"#ffffff"});
    } else if (screen === "resources") {
      tg.BackButton.show();
      tg.MainButton.setParams({text:"মক টেস্ট শুরু করুন", is_visible:true, color:"#0f766e", text_color:"#ffffff"});
    } else if (screen === "quiz") {
      if (current > 0) tg.BackButton.show(); else tg.BackButton.hide();
      var last = quiz && current === quiz.qs.length - 1;
      tg.MainButton.setParams({text:last ? (readOnlyMode ? "শেষ করুন" : "সাবমিট করুন") : "পরবর্তী", is_visible:true, color:"#0f766e", text_color:"#ffffff"});
    } else if (screen === "result") {
      tg.BackButton.show();
      tg.MainButton.setParams({text:"ড্যাশবোর্ড দেখুন", is_visible:true, color:"#2563eb", text_color:"#ffffff"});
    } else {
      tg.BackButton.hide();
      tg.MainButton.hide();
    }
  }

  function loadHome(){
    retryAction = loadHome;
    document.title = "পরীক্ষা প্রস্তুতি";
    byId("brand-title").textContent = "পরীক্ষা প্রস্তুতি";
    byId("quiz-id-pill").textContent = "প্রস্তুতি হাব";
    byId("loading-message").textContent = "সাম্প্রতিক কুইজ লোড হচ্ছে...";
    byId("home-retry-wrap").classList.add("hidden");
    show("loading");
    fetchWithTimeout(api("/api/quizzes/recent?limit=26"))
      .then(function(resp){ return jsonOrThrow(resp, "Recent quizzes API"); })
      .then(function(data){ renderHome(Array.isArray(data.items) ? data.items : []); })
      .catch(function(){
        renderHome([]);
        byId("quiz-catalogue").textContent = "";
        var state = document.createElement("div");
        state.className = "home-state";
        state.textContent = "সাম্প্রতিক কুইজ এখন লোড করা যাচ্ছে না। অনুশীলন, মক ও অগ্রগতির অংশ ব্যবহার করতে পারেন।";
        byId("quiz-catalogue").appendChild(state);
        byId("home-retry-wrap").classList.remove("hidden");
      });
  }

  function renderHome(items){
    var catalogue = byId("quiz-catalogue");
    if (requestedHomeSubject) items = items.filter(function(item){ return item.subjectKey === requestedHomeSubject; });
    catalogue.textContent = "";
    byId("home-count").textContent = items.length ? bn(items.length) + "টি উপলভ্য" : "";
    if (!items.length) {
      var empty = document.createElement("div");
      empty.className = "home-state";
      empty.textContent = requestedHomeSubject ? "আপনার নির্বাচিত বিষয়ে এখন কোনো প্রকাশিত কুইজ নেই। অন্য বিষয় বা মক পরীক্ষা খুলুন।" : "এখনও কোনো প্রকাশিত কুইজ নেই। প্রথম কুইজ প্রকাশ হলে এখানে দেখা যাবে।";
      catalogue.appendChild(empty);
    }
    items.forEach(function(item){
      var link = document.createElement("a");
      link.className = "quiz-card";
      link.href = telegramUrl("./?quiz=" + encodeURIComponent(item.quizId || ""));
      var copy = document.createElement("div");
      var title = document.createElement("strong");
      var chapter = document.createElement("span");
      var when = document.createElement("time");
      title.textContent = item.subjectName || "দৈনিক কুইজ";
      chapter.textContent = item.chapter || "প্রতিযোগিতামূলক পরীক্ষার প্রস্তুতি";
      when.dateTime = item.quizDate || "";
      when.textContent = formatHomeDate(item.quizDate);
      copy.append(title, chapter);link.append(copy, when);catalogue.appendChild(link);
    });
    show("home");
  }

  function formatHomeDate(value){
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return "কুইজ খুলুন";
    try {
      return new Intl.DateTimeFormat("bn-IN", {day:"numeric", month:"short"})
        .format(new Date(value + "T12:00:00Z"));
    } catch(e) { return bn(value); }
  }

  function loadQuiz(){
    retryAction = loadQuiz;
    document.title = "আজকের মক টেস্ট";
    byId("brand-title").textContent = "দৈনিক মক টেস্ট";
    byId("btn-retry").textContent = "আবার চেষ্টা করুন";
    show("loading");
    byId("loading-message").textContent = "কুইজ তৈরি/লোড হচ্ছে...";
    fetchWithTimeout(api("/api/quiz/" + encodeURIComponent(quizId)))
      .then(function(resp){ return jsonOrThrow(resp, "Quiz API"); })
      .then(function(data){
        if (!data.qs || data.qs.length !== 10) throw new Error("Quiz must contain exactly 10 questions");
        quiz = data;
        legacyLocal = !(data.capabilities && data.capabilities.submission === true);
        answers = quiz.qs.map(function(){ return null; });
        if (!legacyLocal && requestedAttemptId) loadAttemptResult(requestedAttemptId);
        else renderIntro();
      })
      .catch(function(err){
        console.error(err);
        if (err.status === 404) {
          loadLegacyQuiz();
          return;
        }
        showError(err.message || "কুইজ লোড করা যায়নি। একটু পরে আবার চেষ্টা করুন।");
      });
  }

  function loadAttemptResult(value){
    retryAction = function(){ loadAttemptResult(value); };
    byId("btn-retry").textContent = "ফল আবার লোড করুন";
    show("loading");
    byId("loading-message").textContent = "আপনার ফলাফল লোড হচ্ছে...";
    fetchWithTimeout(api("/api/quiz/" + encodeURIComponent(quizId) + "/attempt/" + encodeURIComponent(value)), {
      headers:{"X-Telegram-Init-Data":isTelegram ? tg.initData : ""}
    })
      .then(function(resp){ return jsonOrThrow(resp, "Attempt result API"); })
      .then(function(result){ attemptId = value; discardDraft(); renderResult(result); })
      .catch(function(err){
        console.error(err);
        if (err.status === 401) {
          showError("ফল দেখতে Telegram-এর কুইজ বাটন থেকে Mini App খুলুন।");
          return;
        }
        if (err.status === 404) {
          showError("এই কুইজে আপনার সংরক্ষিত ফলটি পাওয়া যায়নি। নতুন করে পরীক্ষা দিতে পারেন।");
          return;
        }
        showError("ফলাফল এখন লোড করা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।");
      });
  }

  function loadLegacyQuiz(){
    fetchWithTimeout("quizzes/" + encodeURIComponent(quizId) + ".json?v=" + Date.now(), {cache:"no-store"})
      .then(function(resp){
        if (!resp.ok) throw new Error("Legacy quiz returned " + resp.status);
        return resp.json();
      })
      .then(function(data){
        if (!data.qs || data.qs.length !== 10) throw new Error("Quiz must contain exactly 10 questions");
        quiz = data;
        legacyLocal = true;
        answers = quiz.qs.map(function(){ return null; });
        renderIntro();
      })
      .catch(function(err){
        console.error(err);
        showError(buildMissingQuizMessage());
      });
  }

  function buildMissingQuizMessage(){
    return "এই কুইজটি এখনও পাওয়া যাচ্ছে না। কুইজ তৈরি বা পুনরুদ্ধার চলছে—কিছুক্ষণ পরে আবার চেষ্টা করুন।";
  }

  function renderIntro(){
    var meta = quiz.meta || {};
    var marking = markingScheme();
    byId("intro-title").textContent = meta.chapter || "আজকের মক টেস্ট";
    byId("intro-subject").textContent = meta.subject || "মক টেস্ট";
    byId("intro-count").textContent = bn(quiz.qs.length) + "টি";
    byId("intro-time").textContent = quizMode === "practice" ? "সময়সীমাহীন অনুশীলন" : bn(Math.max(5, quiz.qs.length)) + " মিনিট";
    byId("intro-marking").textContent = marking.negativeMarking
      ? "+" + bn(formatScore(marking.rightMarks)) + " / −" + bn(formatScore(marking.wrongPenalty))
      : "নেগেটিভ নেই";
    byId("fallback-box").classList.toggle("hidden", !legacyLocal);
    byId("btn-start").classList.toggle("hidden", legacyLocal);
    byId("btn-prepare").classList.toggle("hidden", legacyLocal);
    byId("resume-box").classList.toggle("hidden", legacyLocal || !readDraft());
    show("intro");
  }

  function loadResources(){
    if (legacyLocal) return;
    show("resources");
    byId("resource-status").textContent = "যাচাই করা রিসোর্স লোড হচ্ছে...";
    byId("resource-list").textContent = "";
    fetchWithTimeout(api("/api/quiz/" + encodeURIComponent(quizId) + "/resources"))
      .then(function(resp){ return jsonOrThrow(resp, "Learning resources API"); })
      .then(renderResources)
      .catch(function(err){
        console.error(err);
        byId("resource-status").textContent = "রিসোর্স এখন লোড করা যায়নি। কোনো লাইভ সার্চ করা হয়নি; পরে আবার চেষ্টা করুন।";
        renderResourceTopics(fallbackResourceTopics());
      });
  }

  function renderResources(data){
    var topics = data && Array.isArray(data.topics) ? data.topics : [];
    var count = topics.reduce(function(total, topic){
      return total + (Array.isArray(topic.resources) ? topic.resources.length : 0);
    }, 0);
    byId("resource-status").textContent = count
      ? bn(count) + "টি যাচাই করা রিসোর্স পাওয়া গেছে।"
      : "এই মাইক্রো-টপিকগুলোর যাচাই করা রিসোর্স এখনও প্রস্তুত হচ্ছে। কোনো লাইভ সার্চ করা হয়নি।";
    renderResourceTopics(topics.length ? topics : fallbackResourceTopics());
  }

  function renderResourceTopics(topics){
    var list = byId("resource-list");
    list.textContent = "";
    if (!topics.length) {
      var message = document.createElement("p");
      message.className = "resource-empty";
      message.textContent = "এই কুইজে এখনও কোনো স্বাভাবিকীকৃত মাইক্রো-টপিক পাওয়া যায়নি।";
      list.appendChild(message);
      return;
    }
    topics.forEach(function(topic){
      var card = document.createElement("article");
      card.className = "resource-topic";
      var heading = document.createElement("h3");
      heading.textContent = topic.microTopic || topic.microTopicKey || "মাইক্রো-টপিক";
      card.appendChild(heading);
      var chapter = document.createElement("small");
      chapter.textContent = topic.chapter || (quiz.meta && quiz.meta.chapter) || "";
      card.appendChild(chapter);
      var resources = Array.isArray(topic.resources) ? topic.resources : [];
      if (!resources.length) {
        var empty = document.createElement("p");
        empty.className = "resource-empty";
        empty.textContent = "এই টপিকের রিসোর্স যাচাই চলছে।";
        card.appendChild(empty);
      } else {
        var links = document.createElement("div");
        links.className = "resource-links";
        resources.forEach(function(resource){
          if (!resource.url || resource.url.indexOf("https://") !== 0) return;
          var link = document.createElement("a");
          link.className = "resource-link";
          link.href = resource.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          var badge = document.createElement("span");
          badge.className = "resource-badge";
          badge.textContent = languageLabel(resource.language) + " · " + resourceTypeLabel(resource.type);
          link.appendChild(badge);
          var title = document.createElement("strong");
          title.textContent = resource.title || "পড়ার রিসোর্স";
          link.appendChild(title);
          var source = document.createElement("small");
          source.textContent = resource.source || resource.domain || "যাচাই করা উৎস";
          link.appendChild(source);
          links.appendChild(link);
          if (isTelegram && resource.id) {
            var bookmark = document.createElement("button");
            bookmark.type = "button";
            bookmark.className = "btn btn-secondary";
            bookmark.textContent = "☆ রিসোর্স বুকমার্ক";
            bookmark.addEventListener("click", function(){ setBookmark(bookmark, "resource", resource.id); });
            links.appendChild(bookmark);
            links.appendChild(resourceFeedbackControl(resource));
          }
        });
        card.appendChild(links);
      }
      list.appendChild(card);
    });
  }

  function resourceFeedbackControl(resource){
    var details = document.createElement("details");
    details.className = "resource-feedback";
    var summary = document.createElement("summary");
    summary.textContent = "রিসোর্সে সমস্যা জানান";
    details.appendChild(summary);
    var fields = document.createElement("div");
    fields.className = "resource-feedback-fields";
    var select = document.createElement("select");
    [
      ["video_unavailable","ভিডিও চলছে না"],
      ["article_unavailable","লিংক খুলছে না"],
      ["not_useful","সহায়ক নয়"],
      ["wrong_language","ভুল ভাষা"],
      ["topic_mismatch","টপিক মিলছে না"],
      ["low_quality","মান কম"]
    ].forEach(function(option){
      var row = document.createElement("option");
      row.value = option[0];
      row.textContent = option[1];
      select.appendChild(row);
    });
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "পাঠান";
    var message = document.createElement("div");
    message.className = "resource-feedback-message";
    message.setAttribute("aria-live", "polite");
    button.addEventListener("click", function(){
      button.disabled = true;
      message.textContent = "পাঠানো হচ্ছে...";
      fetchWithTimeout(api("/api/resources/" + encodeURIComponent(resource.id) + "/feedback"), {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({initData:tg.initData, feedbackType:select.value})
      }).then(function(resp){ return jsonOrThrow(resp, "Resource feedback API"); })
        .then(function(){ message.textContent = "ধন্যবাদ—মতামতটি যাচাইয়ের জন্য রাখা হয়েছে।"; })
        .catch(function(){ message.textContent = "মতামত পাঠানো যায়নি। পরে আবার চেষ্টা করুন।"; })
        .then(function(){ button.disabled = false; });
    });
    fields.append(select, button, message);
    details.appendChild(fields);
    return details;
  }

  function fallbackResourceTopics(){
    var seen = {};
    return (quiz && quiz.qs ? quiz.qs : []).reduce(function(topics, question){
      var key = question.microTopicKey || "";
      if (!key || seen[key]) return topics;
      seen[key] = true;
      topics.push({
        chapter: question.chapter || (quiz.meta && quiz.meta.chapter) || "",
        microTopicKey: key,
        microTopic: key,
        resources: []
      });
      return topics;
    }, []);
  }

  function languageLabel(language){
    return language === "bn" ? "বাংলা" : language === "hi" ? "হিন্দি" : "English";
  }

  function resourceTypeLabel(type){
    var labels = {youtube:"YouTube", article:"Article", official_webpage:"Official", pdf:"PDF", study_note:"Study note", internal_note:"Note"};
    return labels[type] || "Resource";
  }

  function startQuiz(previewOnly){
    if (legacyLocal && previewOnly !== true) {
      loadQuiz();
      return;
    }
    // A public browser URL cannot supply Telegram-signed identity. Keep it
    // genuinely read-only instead of starting a timer that can never submit.
    readOnlyMode = legacyLocal || !isTelegram || previewOnly === true;
    clearResultLocation();
    discardDraft();
    attemptId = newAttemptId();
    serverAttemptStarted = false;
    serverStartPromise = null;
    answers = quiz.qs.map(function(){ return null; });
    markedForReview = quiz.qs.map(function(){ return false; });
    responseTimes = quiz.qs.map(function(){ return null; });
    current = 0;
    totalSeconds = Math.max(300, quiz.qs.length * 60);
    timeLeft = totalSeconds;
    startedAt = Date.now();
    ensureServerAttemptStarted().catch(function(){});
    questionStartedAt = Date.now();
    prepareQuizHeader();
    renderQuestion();
    startTimer();
    show("quiz");
    saveDraft();
  }

  function ensureServerAttemptStarted(){
    if (readOnlyMode || serverAttemptStarted) return Promise.resolve();
    if (serverStartPromise) return serverStartPromise;
    serverStartPromise = fetchWithTimeout(api("/api/quiz/" + encodeURIComponent(quizId) + "/attempts/start"), {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        initData:isTelegram ? tg.initData : "",
        attemptId:attemptId
      })
    }).then(function(resp){ return jsonOrThrow(resp, "Attempt start API"); })
      .then(function(){ serverAttemptStarted = true; })
      .catch(function(error){
        serverStartPromise = null;
        throw error;
      });
    return serverStartPromise;
  }

  function prepareQuizHeader(){
    byId("quiz-subject").textContent = (quiz.meta && quiz.meta.subject) || "মক টেস্ট";
    byId("quiz-chapter").textContent = (quiz.meta && quiz.meta.chapter) || "";
    var marking = markingScheme();
    var mode = quizMode === "practice" ? "অনুশীলন মোড · সময়সীমা নেই" : "সময়বদ্ধ মোড";
    byId("mode-label").textContent = mode + (
      marking.negativeMarking
        ? " · ভুলে −" + bn(formatScore(marking.wrongPenalty))
        : ""
    );
  }

  function renderQuestion(){
    var q = quiz.qs[current];
    byId("q-index").textContent = "প্রশ্ন " + bn(current + 1) + " / " + bn(quiz.qs.length);
    byId("answered-count").textContent = "উত্তর " + bn(answers.filter(function(v){ return v !== null; }).length);
    byId("q-text").textContent = q.q;
    var progress = byId("progress-fill");
    progress.max = quiz.qs.length;
    progress.value = current + 1;

    var wrap = byId("options-wrap");
    wrap.innerHTML = "";
    q.o.forEach(function(label, index){
      var button = document.createElement("button");
      button.className = "option" + (answers[current] === index ? " selected" : "");
      button.type = "button";
      button.innerHTML = '<span class="key">' + LETTERS[index] + '</span><span class="label"></span>';
      button.querySelector(".label").textContent = label;
      button.addEventListener("click", function(){
        answers[current] = index;
        haptic("select");
        saveDraft();
        renderQuestion();
      });
      wrap.appendChild(button);
    });
    byId("btn-prev").disabled = current === 0;
    byId("btn-next").textContent = current === quiz.qs.length - 1 ? (readOnlyMode ? "শেষ করুন" : "সাবমিট করুন") : "পরবর্তী";
    syncTelegramButtons();
    renderNavigator();
    var marked = !!markedForReview[current];
    byId("btn-mark").classList.toggle("active", marked);
    byId("btn-mark").setAttribute("aria-pressed", marked ? "true" : "false");
    byId("btn-mark").textContent = marked ? "★ রিভিউয়ের জন্য চিহ্নিত" : "☆ রিভিউয়ের জন্য চিহ্নিত করুন";
  }

  function renderNavigator(){
    var nav = byId("question-navigator");
    nav.textContent = "";
    quiz.qs.forEach(function(_, index){
      var button = document.createElement("button");
      button.type = "button";
      button.className = "nav-q" + (answers[index] !== null ? " answered" : "") + (markedForReview[index] ? " marked" : "") + (index === current ? " current" : "");
      button.textContent = bn(index + 1);
      button.setAttribute("aria-label", "প্রশ্ন " + bn(index + 1) + (answers[index] !== null ? ", উত্তর দেওয়া" : ", উত্তর বাকি") + (markedForReview[index] ? ", রিভিউ চিহ্নিত" : ""));
      button.addEventListener("click", function(){ moveToQuestion(index); });
      nav.appendChild(button);
    });
  }

  function toggleMarked(){
    markedForReview[current] = !markedForReview[current];
    haptic("select");
    saveDraft();
    renderQuestion();
  }

  function trackCurrentTime(){
    if (!questionStartedAt || !responseTimes.length) return;
    var elapsed = Math.max(0, (Date.now() - questionStartedAt) / 1000);
    responseTimes[current] = Math.min(3600, Number(responseTimes[current] || 0) + elapsed);
    questionStartedAt = Date.now();
  }

  function moveToQuestion(index){
    if (index === current) return;
    trackCurrentTime();
    current = Math.max(0, Math.min(quiz.qs.length - 1, index));
    questionStartedAt = Date.now();
    saveDraft();
    renderQuestion();
  }

  function startTimer(){
    clearInterval(timerHandle);
    if (readOnlyMode || quizMode === "practice") {
      byId("timer").textContent = readOnlyMode ? "Preview" : "Practice";
      byId("timer").classList.remove("low");
      return;
    }
    tick();
    timerHandle = setInterval(function(){
      timeLeft -= 1;
      tick();
      if (timeLeft % 5 === 0) saveDraft();
      if (timeLeft <= 0) finishQuiz(true);
    }, 1000);
  }

  function tick(){
    var safe = Math.max(0, timeLeft);
    var mm = Math.floor(safe / 60);
    var ss = safe % 60;
    var timer = byId("timer");
    timer.textContent = bn(pad2(mm) + ":" + pad2(ss));
    timer.classList.toggle("low", safe <= Math.max(30, totalSeconds * .15));
  }

  function goPrev(){
    if (current > 0) {
      moveToQuestion(current - 1);
    }
  }

  function nextOrFinish(){
    if (current < quiz.qs.length - 1) {
      moveToQuestion(current + 1);
    } else {
      finishQuiz();
    }
  }

  function finishQuiz(confirmed){
    if (submitting) return;
    if (readOnlyMode) {
      retryAction = loadQuiz;
      byId("btn-retry").textContent = "লাইভ কুইজ আবার চেষ্টা করুন";
      showError("এটি শুধু প্রশ্ন প্রিভিউ। উত্তর যাচাই, স্কোর ও র‍্যাঙ্ক পেতে Telegram থেকে কুইজটি খুলুন।");
      return;
    }
    if (confirmed !== true) {
      showSubmitConfirmation();
      return;
    }
    trackCurrentTime();
    submitting = true;
    retryAction = finishQuiz;
    clearInterval(timerHandle);
    show("loading");
    byId("loading-message").textContent = "উত্তর সাবমিট হচ্ছে...";
    ensureServerAttemptStarted().catch(function(){
      // The server accepts legacy submission, but marks all timing untrusted.
    }).then(function(){ return fetchWithTimeout(api("/api/quiz/" + encodeURIComponent(quizId) + "/submit"), {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        initData: isTelegram ? tg.initData : "",
        answers: answers,
        attemptId: attemptId,
        durationSeconds: Math.min(86400, Math.max(0, Math.round((Date.now() - startedAt) / 1000))),
        responseTimes: responseTimes.map(function(value){ return value === null ? null : Math.round(value * 100) / 100; }),
        markedForReview: markedForReview
      })
    }); })
      .then(function(resp){
        if (!resp.ok) {
          return jsonOrThrow(resp, "Submit API");
        }
        return resp.json();
      })
      .then(function(result){ submitting = false; discardDraft(); rememberResultLocation(result.attemptId || attemptId); renderResult(result); })
      .catch(function(err){
        submitting = false;
        console.error(err);
        retryAction = finishQuiz;
        byId("btn-retry").textContent = "আবার চেষ্টা করুন";
        if (err.status === 401) {
          showError("স্কোর জমা দিতে Telegram-এর কুইজ বাটন থেকে Mini App খুলুন।");
          return;
        }
        showError("উত্তর জমা করা যায়নি। একটু পরে আবার চেষ্টা করুন।");
      });
  }

  function showSubmitConfirmation(){
    var answered = answers.filter(function(value){ return value !== null; }).length;
    var unanswered = answers.length - answered;
    var marked = markedForReview.filter(Boolean).length;
    var marking = markingScheme();
    byId("submit-summary").textContent =
      "আপনি " + bn(answered) + "টি প্রশ্নের উত্তর দিয়েছেন। " +
      bn(unanswered) + "টি প্রশ্ন এখনও বাকি। " +
      bn(marked) + "টি প্রশ্ন রিভিউয়ের জন্য চিহ্নিত।" +
      (marking.negativeMarking
        ? " প্রতিটি ভুল উত্তরে " + bn(formatScore(marking.wrongPenalty)) + " নম্বর কাটা হবে।"
        : "");
    byId("submit-modal").classList.remove("hidden");
    byId("btn-submit-back").focus();
  }

  function hideSubmitConfirmation(){
    byId("submit-modal").classList.add("hidden");
  }

  function openDashboard(){
    navigateTelegram("dashboard.html?quiz=" + encodeURIComponent(quizId));
  }

  function openWrongPractice(){
    var subject = quiz && quiz.meta ? (quiz.meta.subject_key || quiz.meta.subjectKey || "") : "";
    navigateTelegram("practice.html?source=wrong" + (subject ? "&subject=" + encodeURIComponent(subject) : ""));
  }

  function openRevisionPractice(){
    navigateTelegram("practice.html?source=due");
  }

  function newAttemptId(){
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    if (!window.crypto || typeof window.crypto.getRandomValues !== "function") {
      throw new Error("এই ব্রাউজার নতুন চেষ্টার নিরাপদ পরিচয় তৈরি করতে পারে না। Telegram আপডেট করে আবার চেষ্টা করুন।");
    }
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    var hex = Array.prototype.map.call(bytes, function(value){ return value.toString(16).padStart(2,"0"); }).join("");
    return hex.slice(0,8)+"-"+hex.slice(8,12)+"-"+hex.slice(12,16)+"-"+hex.slice(16,20)+"-"+hex.slice(20);
  }

  function renderResult(result){
    if (validAttemptId(result.attemptId)) attemptId = result.attemptId.toLowerCase();
    rememberResultLocation(attemptId);
    var durationValue = result.duration_seconds === undefined ? result.durationSeconds : result.duration_seconds;
    var attemptNumber = result.attempt_number === undefined ? result.attemptNumber : result.attempt_number;
    var bestScore = result.best_score === undefined ? result.bestScore : result.best_score;
    var bestNetScore = result.best_net_score === undefined ? result.bestNetScore : result.best_net_score;
    var correct = Number(result.correct === undefined ? result.score : result.correct) || 0;
    var answered = Number(result.answered) || 0;
    var incorrect = Number(result.incorrect === undefined ? answered - correct : result.incorrect) || 0;
    var netScore = Number(result.net_score === undefined ? result.netScore : result.net_score);
    if (!Number.isFinite(netScore)) netScore = Number(result.score) || 0;
    var negativeMarks = Number(
      result.negative_marks === undefined ? result.negativeMarks : result.negative_marks
    );
    if (!Number.isFinite(negativeMarks)) negativeMarks = Math.max(0, correct - netScore);
    var pct = result.total ? Math.round(correct / result.total * 100) : 0;
    var netPct = result.total
      ? Math.max(0, Math.min(100, netScore / result.total * 100))
      : 0;
    var duration = durationValue === null || durationValue === undefined
      ? Math.max(0, Math.round((Date.now() - startedAt) / 1000))
      : durationValue;
    byId("score-ring").setAttribute("stroke-dasharray", netPct + " 100");
    byId("score-text").textContent = bn(formatScore(netScore)) + "/" + bn(result.total);
    byId("result-title").textContent = resultTitle(pct);
    byId("result-subtitle").textContent =
      "চেষ্টা " + bn(attemptNumber || 1) + ": নেট স্কোর " +
      bn(formatScore(netScore)) + "/" + bn(result.total) +
      "। আপনার সেরা নেট স্কোর " +
      bn(formatScore(bestNetScore === undefined ? (
        bestScore === undefined ? netScore : bestScore
      ) : bestNetScore)) +
      "/" + bn(result.total) + "; র‍্যাঙ্ক: " + bn(result.rank || "-") + " / " +
      bn(result.participants || 0) + "। ড্যাশবোর্ডে সর্বশেষ চেষ্টার স্কোর দেখাবে। আবার পরীক্ষা দিতে পারেন।";
    byId("result-correct").textContent = bn(correct);
    byId("result-incorrect").textContent = bn(incorrect);
    byId("result-negative").textContent = "−" + bn(formatScore(negativeMarks));
    byId("result-accuracy").textContent = bn(pct) + "%";
    byId("result-time").textContent = bn(Math.floor(duration / 60) + ":" + pad2(duration % 60));
    byId("result-average").textContent = bn(result.total ? Math.round(duration / result.total) : 0) + " সেকেন্ড";
    byId("result-unanswered").textContent = bn(Math.max(0, result.total - answered));

    var list = byId("review-list");
    list.innerHTML = "";
    (result.review || []).forEach(function(item, index){
      var selected = item.selectedIndex;
      var correct = item.correctIndex;
      var row = document.createElement("article");
      row.className = "review " + (item.isCorrect ? "ok" : "bad");
      row.innerHTML =
        '<h3></h3>' +
        '<p class="answer selected"></p>' +
        '<p class="answer correct"></p>' +
        '<p class="explanation"></p>' +
        '<p class="source" hidden></p>' +
        '<button type="button" class="btn btn-secondary bookmark-submit">☆ প্রশ্ন বুকমার্ক</button>' +
        '<details class="report-box"><summary>প্রশ্নটি রিপোর্ট করুন</summary>' +
          '<div class="report-fields">' +
            '<select aria-label="রিপোর্টের কারণ">' +
              '<option value="wrong_answer">সঠিক উত্তর ভুল</option>' +
              '<option value="multiple_correct">একাধিক সঠিক উত্তর</option>' +
              '<option value="ambiguous">প্রশ্ন অস্পষ্ট</option>' +
              '<option value="incorrect_explanation">ব্যাখ্যা ভুল</option>' +
              '<option value="language_spelling">ভাষা বা বানান</option>' +
              '<option value="outdated">তথ্য পুরোনো</option>' +
              '<option value="outside_syllabus">সিলেবাসের বাইরে</option>' +
              '<option value="broken_source">সোর্স লিংক কাজ করছে না</option>' +
              '<option value="duplicate_question">একই প্রশ্ন পুনরাবৃত্তি</option>' +
              '<option value="translation_error">অনুবাদ ভুল</option>' +
              '<option value="other">অন্যান্য</option>' +
            '</select>' +
            '<textarea maxlength="1000" placeholder="সংক্ষিপ্ত বিস্তারিত (ঐচ্ছিক)"></textarea>' +
            '<button type="button" class="report-submit">রিপোর্ট পাঠান</button>' +
            '<p class="report-message" aria-live="polite"></p>' +
          '</div></details>';
      row.querySelector("h3").textContent = bn(index + 1) + ". " + item.q;
      row.querySelector(".selected").textContent =
        "তোমার উত্তর: " + (selected === null || selected === undefined ? "উত্তর দেওয়া হয়নি" : item.o[selected]);
      row.querySelector(".correct").textContent = "সঠিক উত্তর: " + item.o[correct];
      row.querySelector(".explanation").textContent = item.explanation || "";
      var source = row.querySelector(".source");
      if (item.sourceUrl && /^https:\/\//i.test(item.sourceUrl)) {
        var sourceLink = document.createElement("a");
        sourceLink.href = item.sourceUrl;
        sourceLink.target = "_blank";
        sourceLink.rel = "noopener noreferrer";
        sourceLink.textContent = "সোর্স: " + (item.sourceTitle || item.sourceUrl);
        source.appendChild(sourceLink);
        source.hidden = false;
      }
      row.querySelector(".report-submit").addEventListener("click", function(){
        submitQuestionReport(row, item);
      });
      row.querySelector(".bookmark-submit").addEventListener("click", function(){
        setBookmark(row.querySelector(".bookmark-submit"), "question", item.questionId);
      });
      list.appendChild(row);
    });
    haptic(pct >= 50 ? "success" : "warning");
    show("result");
  }

  function setBookmark(button, itemType, itemId){
    if (!isTelegram || !itemId || button.disabled) return;
    button.disabled = true;
    fetchWithTimeout(api("/api/me/bookmarks"), {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({initData:tg.initData,itemType:itemType,itemId:itemId,active:true})
    })
      .then(function(resp){ return jsonOrThrow(resp, "Bookmark API"); })
      .then(function(){ button.textContent = "★ বুকমার্ক করা হয়েছে"; haptic("success"); })
      .catch(function(){ button.disabled = false; button.textContent = "বুকমার্ক করা যায়নি"; });
  }

  function submitQuestionReport(row, item){
    var button = row.querySelector(".report-submit");
    var message = row.querySelector(".report-message");
    if (!item.questionId || !attemptId || button.disabled) return;
    var reason = row.querySelector(".report-fields select").value;
    var details = row.querySelector(".report-fields textarea").value;
    if (reason === "other" && !details.trim()) {
      message.textContent = "অন্যান্য কারণের জন্য সংক্ষিপ্ত বিস্তারিত লিখুন।";
      return;
    }
    button.disabled = true;
    message.textContent = "রিপোর্ট পাঠানো হচ্ছে...";
    fetchWithTimeout(api("/api/questions/" + encodeURIComponent(item.questionId) + "/report"), {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        initData: isTelegram ? tg.initData : "",
        quizId: quizId,
        attemptId: attemptId,
        reason: reason,
        details: details
      })
    })
      .then(function(resp){ return resp.ok ? resp.json() : jsonOrThrow(resp, "Report API"); })
      .then(function(){
        message.textContent = "রিপোর্ট গ্রহণ করা হয়েছে। ধন্যবাদ।";
        haptic("success");
      })
      .catch(function(err){
        button.disabled = false;
        if (err.status === 409) message.textContent = "এই চেষ্টায় প্রশ্নটি আগে রিপোর্ট করা হয়েছে।";
        else if (err.status === 401) message.textContent = "রিপোর্ট করতে Telegram থেকে কুইজটি খুলুন।";
        else if (err.status === 429) message.textContent = "অনেক রিপোর্ট হয়েছে; কিছুক্ষণ পরে চেষ্টা করুন।";
        else message.textContent = "রিপোর্ট পাঠানো যায়নি। পরে আবার চেষ্টা করুন।";
      });
  }

  function resultTitle(pct){
    if (pct >= 80) return "দারুণ প্রস্তুতি";
    if (pct >= 50) return "ভালো, আরও ধারালো করো";
    return "পুনরাবৃত্তি দরকার";
  }

  function showError(message){
    clearInterval(timerHandle);
    byId("error-message").textContent = message;
    show("error");
  }

  function haptic(kind){
    if (!isTelegram || !tg.HapticFeedback) return;
    try {
      if (kind === "select") tg.HapticFeedback.selectionChanged();
      else tg.HapticFeedback.notificationOccurred(kind);
    } catch(e){}
  }
})();
