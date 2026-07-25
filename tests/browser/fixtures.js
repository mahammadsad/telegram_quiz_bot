const { expect } = require("@playwright/test");

const QUIZ_ID = "20260725-history";
const ATTEMPT_ONE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ATTEMPT_TWO = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function questionId(index) {
  return `20000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
}

function quizPayload() {
  return {
    meta: {
      quiz_id: QUIZ_ID,
      subject: "ইতিহাস",
      subject_key: "history",
      chapter: "আধুনিক ভারতের স্বাধীনতা আন্দোলন ও সাংবিধানিক বিকাশ",
      date: "2026-07-25",
    },
    capabilities: { submission: true, source: "api" },
    qs: Array.from({ length: 10 }, (_, index) => ({
      q:
        index === 0
          ? "বাংলার নবজাগরণ, স্বাধীনতা আন্দোলন এবং আধুনিক ভারতের সাংবিধানিক বিকাশের দীর্ঘ ধারাবাহিকতায় নিচের কোন ঘটনাটি সঠিক সময়ক্রমে ঘটেছিল?"
          : `ইতিহাসের যাচাইকৃত প্রশ্ন ${index + 1}-এর সঠিক প্রসঙ্গ কোনটি?`,
      o: [
        `বিকল্প ক — প্রশ্ন ${index + 1}`,
        `বিকল্প খ — প্রশ্ন ${index + 1}`,
        `বিকল্প গ — প্রশ্ন ${index + 1}`,
        `বিকল্প ঘ — প্রশ্ন ${index + 1}`,
      ],
      subjectKey: "history",
      chapter: "আধুনিক ভারত",
      microTopicKey: "history:modern-india:core",
    })),
  };
}

function resultPayload(attemptId = ATTEMPT_ONE, attemptNumber = 1) {
  return {
    attemptId,
    score: 7,
    total: 10,
    answered: 10,
    rank: 27,
    participants: 48,
    durationSeconds: 142,
    attemptNumber,
    bestScore: 8,
    review: quizPayload().qs.map((question, index) => ({
      questionId: questionId(index),
      q: question.q,
      o: question.o,
      selectedIndex: index % 4,
      correctIndex: (index + 1) % 4,
      isCorrect: index < 7,
      explanation: `সাবমিটের পর দৃশ্যমান যাচাইকৃত ব্যাখ্যা ${index + 1}।`,
      sourceUrl: "https://ncert.nic.in/example",
      sourceTitle: "যাচাইকৃত সরকারি উৎস",
    })),
  };
}

function preferencesPayload() {
  return {
    targetExams: ["WBCS", "SSC"],
    preferredSubjects: ["history", "geography"],
    dailyQuestionTarget: 30,
    preferredLanguage: "bn",
    difficultyPreference: "adaptive",
    quizMode: "timed",
    leaderboardVisible: true,
    publicDisplayName: "মোবাইল পরীক্ষার্থী",
    usernameVisible: false,
    dailyReminderEnabled: false,
    revisionSoundEnabled: true,
    revisionVibrationEnabled: false,
  };
}

function dashboardPayload() {
  return {
    identity: {
      displayName: "মোবাইল পরীক্ষার্থী",
      username: "@mobile_learner",
      initials: "মপ",
      isCurrentUser: true,
      label: "এটি আপনার ড্যাশবোর্ড",
    },
    dailyTarget: 30,
    todayAnswered: 18,
    totalAnswered: 126,
    correctAnswers: 91,
    incorrectAnswers: 35,
    accuracy: 72,
    dueReviews: 4,
    revisionDueToday: 4,
    currentStreak: 6,
    longestStreak: 12,
    totalQuizzesCompleted: 14,
    currentOverallRank: 27,
    weeklyRank: 11,
    averageImprovement: 8,
    revisionMastered: 19,
    revisionTotal: 25,
    revisionCompletion: 76,
    overdueQuestions: 2,
    weakQuestions: 5,
    recentlyMastered: 3,
    averageResponseTimeSeconds: 14,
    bookmarkedQuestions: 1,
    questionsReported: 2,
    strongestSubject: { subjectKey: "history", accuracy: 86 },
    weakestSubject: { subjectKey: "geography", accuracy: 48 },
    strongestTopics: [{ chapter: "আধুনিক ভারত" }],
    subjectRevisionCounts: [
      { subjectKey: "history", due: 2 },
      { subjectKey: "geography", due: 2 },
    ],
    progressOverTime: [
      { date: "2026-07-23", answered: 12 },
      { date: "2026-07-24", answered: 18 },
    ],
    subjectPerformance: [
      { subjectKey: "history", accuracy: 86 },
      { subjectKey: "geography", accuracy: 48 },
    ],
    weakestTopics: [
      {
        subjectKey: "geography",
        chapter: "ভারতের ভূগোল",
        microTopicKey: "geography:india",
        accuracy: 42,
      },
    ],
    chapterPerformance: [
      { subjectKey: "history", chapter: "আধুনিক ভারত", accuracy: 82 },
    ],
    recentQuizzes: [
      {
        quizId: QUIZ_ID,
        completedAt: "2026-07-25T05:30:00Z",
        attemptNumber: 1,
        durationSeconds: 142,
        score: 7,
        total: 10,
      },
    ],
  };
}

function bookmarksPayload({ empty = false } = {}) {
  if (empty) return { questions: [], resources: [] };
  return {
    questions: [
      {
        id: questionId(0),
        q: "বুকমার্ক করা ইতিহাস প্রশ্ন",
        subjectKey: "history",
        chapter: "আধুনিক ভারত",
      },
    ],
    resources: [
      {
        id: "30000000-0000-4000-8000-000000000001",
        title: "যাচাইকৃত ইতিহাস পাঠ",
        source: "NCERT",
        url: "https://ncert.nic.in/example",
      },
    ],
  };
}

function quizLeaderboardPayload() {
  const rows = Array.from({ length: 10 }, (_, index) => ({
    rank: index + 1,
    displayName: `শিক্ষার্থী ${index + 1}`,
    initials: `শ${index + 1}`,
    score: 10 - Math.floor(index / 3),
    total: 10,
    accuracy: 100 - index * 3,
    durationSeconds: 90 + index,
    isCurrentUser: false,
  }));
  return {
    quizId: QUIZ_ID,
    participants: 48,
    rows,
    currentUser: {
      rank: 27,
      displayName: "মোবাইল পরীক্ষার্থী",
      initials: "মপ",
      score: 7,
      total: 10,
      accuracy: 70,
      correct: 7,
      incorrect: 3,
      unanswered: 0,
      durationSeconds: 142,
      percentile: 44,
      rankMovement: 2,
      isCurrentUser: true,
    },
    separatorRequired: true,
  };
}

function typedLeaderboardPayload() {
  return {
    type: "weekly_accuracy",
    participants: 2,
    offset: 0,
    rows: [
      {
        rank: 1,
        displayName: "সাপ্তাহিক প্রথম",
        initials: "সপ",
        value: 91,
        totalAnswered: 42,
        isCurrentUser: false,
      },
      {
        rank: 2,
        displayName: "মোবাইল পরীক্ষার্থী",
        initials: "মপ",
        value: 72,
        totalAnswered: 35,
        isCurrentUser: true,
      },
    ],
  };
}

function practiceQueue(source = "due", { empty = false } = {}) {
  const practice = source === "bookmark";
  return {
    mode: practice ? "practice" : "revision",
    sourceType: source,
    total: empty ? 0 : 2,
    rows: empty
      ? []
      : Array.from({ length: 2 }, (_, index) => ({
          questionId: questionId(index),
          q: `পুনরাবৃত্তির বাংলা প্রশ্ন ${index + 1} — উত্তর দেওয়ার আগে সমাধান গোপন থাকবে।`,
          o: ["প্রথম বিকল্প", "দ্বিতীয় বিকল্প", "তৃতীয় বিকল্প", "চতুর্থ বিকল্প"],
          subjectKey: "history",
          chapter: "আধুনিক ভারত",
          markedForReview: index === 1,
        })),
    questions: empty
      ? []
      : Array.from({ length: 2 }, (_, index) => ({
          id: questionId(index),
          questionId: questionId(index),
          q: `বুকমার্ক অনুশীলনের প্রশ্ন ${index + 1}`,
          o: ["প্রথম বিকল্প", "দ্বিতীয় বিকল্প", "তৃতীয় বিকল্প", "চতুর্থ বিকল্প"],
          subjectKey: "history",
          chapter: "আধুনিক ভারত",
        })),
  };
}

async function installTelegramMock(page, { startParam = QUIZ_ID } = {}) {
  await page.addInitScript(({ injectedStartParam }) => {
    const state = {
      ready: 0,
      expand: 0,
      closingConfirmation: 0,
      mainParams: null,
      mainVisible: false,
      backVisible: false,
      haptics: [],
      audioContexts: 0,
      audioStarts: 0,
      vibrations: [],
    };
    let mainHandler = null;
    let backHandler = null;

    class MockAudioContext {
      constructor() {
        state.audioContexts += 1;
        this.currentTime = 0;
        this.state = "running";
        this.destination = {};
      }
      resume() {
        this.state = "running";
      }
      close() {}
      createOscillator() {
        const oscillator = {
          type: "sine",
          frequency: {
            setValueAtTime() {},
            exponentialRampToValueAtTime() {},
          },
          connect() {},
          start() {
            state.audioStarts += 1;
          },
          stop() {
            setTimeout(() => {
              if (typeof oscillator.onended === "function") oscillator.onended();
            }, 0);
          },
          onended: null,
        };
        return oscillator;
      }
      createGain() {
        return {
          gain: {
            setValueAtTime() {},
            exponentialRampToValueAtTime() {},
          },
          connect() {},
        };
      }
    }

    window.__mobileQa = state;
    window.AudioContext = MockAudioContext;
    window.webkitAudioContext = MockAudioContext;
    Object.defineProperty(navigator, "vibrate", {
      configurable: true,
      value(pattern) {
        state.vibrations.push(pattern);
        return true;
      },
    });
    window.Telegram = {
      WebApp: {
        initData: "deterministic-browser-test",
        initDataUnsafe: { start_param: injectedStartParam },
        ready() {
          state.ready += 1;
        },
        expand() {
          state.expand += 1;
        },
        enableClosingConfirmation() {
          state.closingConfirmation += 1;
        },
        setHeaderColor() {},
        setBackgroundColor() {},
        MainButton: {
          onClick(handler) {
            mainHandler = handler;
          },
          setParams(params) {
            state.mainParams = { ...params };
            state.mainVisible = Boolean(params.is_visible);
          },
          hide() {
            state.mainVisible = false;
          },
        },
        BackButton: {
          onClick(handler) {
            backHandler = handler;
          },
          show() {
            state.backVisible = true;
          },
          hide() {
            state.backVisible = false;
          },
        },
        HapticFeedback: {
          selectionChanged() {
            state.haptics.push("selection");
          },
          notificationOccurred(kind) {
            state.haptics.push(kind);
          },
        },
      },
    };
    window.__triggerMainButton = () => {
      if (mainHandler) mainHandler();
    };
    window.__triggerBackButton = () => {
      if (backHandler) backHandler();
    };
  }, { injectedStartParam: startParam });

  await page.route("https://telegram.org/**", (route) => route.abort());
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("https://fonts.gstatic.com/**", (route) => route.abort());
}

async function installApiMocks(page, options = {}) {
  const state = {
    quizSubmissions: [],
    practiceSubmissions: [],
    reports: [],
    bookmarks: [],
    preferenceSaves: [],
    quizSubmissionCount: 0,
  };
  const source = options.practiceSource || "due";

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (path === `/api/quiz/${QUIZ_ID}` && method === "GET") {
      if (options.quizLoadDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.quizLoadDelayMs));
      }
      return json(quizPayload());
    }
    if (path === `/api/quiz/${QUIZ_ID}/resources` && method === "GET") {
      return json({
        quizId: QUIZ_ID,
        available: true,
        topics: [
          {
            chapter: "আধুনিক ভারত",
            microTopicKey: "history:modern-india:core",
            microTopic: "স্বাধীনতা আন্দোলন",
            resources: [
              {
                id: "30000000-0000-4000-8000-000000000001",
                title: "যাচাইকৃত ইতিহাস পাঠ",
                url: "https://ncert.nic.in/example",
                language: "bn",
                type: "official_webpage",
                source: "NCERT",
              },
            ],
          },
        ],
      });
    }
    if (path === `/api/quiz/${QUIZ_ID}/submit` && method === "POST") {
      const body = request.postDataJSON();
      state.quizSubmissions.push(body);
      state.quizSubmissionCount += 1;
      if (options.quizSubmitDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.quizSubmitDelayMs));
      }
      if (options.failFirstQuizSubmission && state.quizSubmissionCount === 1) {
        return route.abort("failed");
      }
      return json(resultPayload(body.attemptId, state.quizSubmissionCount > 1 ? 2 : 1));
    }
    if (path.startsWith(`/api/quiz/${QUIZ_ID}/attempt/`) && method === "GET") {
      const attemptId = decodeURIComponent(path.split("/").pop());
      return json(resultPayload(attemptId));
    }
    if (path === `/api/quiz/${QUIZ_ID}/leaderboard` && method === "GET") {
      if (options.emptyLeaderboard) {
        return json({
          quizId: QUIZ_ID,
          participants: 0,
          rows: [],
          currentUser: null,
          separatorRequired: false,
        });
      }
      return json(quizLeaderboardPayload());
    }
    if (path.startsWith("/api/leaderboards/") && method === "GET") {
      if (options.emptyLeaderboard) {
        return json({ type: "weekly_accuracy", participants: 0, offset: 0, rows: [] });
      }
      return json(typedLeaderboardPayload());
    }
    if (path === "/api/me/dashboard" && method === "GET") {
      return json(options.emptyDashboard ? {} : dashboardPayload());
    }
    if (path === "/api/me/preferences" && method === "GET") {
      return json({
        ...preferencesPayload(),
        ...(options.preferences || {}),
      });
    }
    if (path === "/api/me/preferences" && method === "PUT") {
      const body = request.postDataJSON();
      state.preferenceSaves.push(body);
      return json(body);
    }
    if (path === "/api/me/bookmarks" && method === "GET") {
      if (source === "bookmark") {
        const queue = practiceQueue("bookmark", {
          empty: Boolean(options.emptyPractice),
        });
        return json({
          mode: queue.mode,
          sourceType: queue.sourceType,
          questions: queue.questions,
          resources: [],
        });
      }
      return json(bookmarksPayload({ empty: Boolean(options.emptyBookmarks) }));
    }
    if (path === "/api/me/bookmarks" && method === "POST") {
      const body = request.postDataJSON();
      state.bookmarks.push(body);
      return json({
        itemType: body.itemType,
        itemId: body.itemId,
        active: body.active,
      });
    }
    if (path === "/api/me/reviews/due" && method === "GET") {
      return json(practiceQueue("due", { empty: Boolean(options.emptyPractice) }));
    }
    if (path === "/api/me/wrong-questions" && method === "GET") {
      return json(
        practiceQueue(source === "bookmark" ? "wrong" : source, {
          empty: Boolean(options.emptyPractice),
        }),
      );
    }
    if (path.endsWith("/report") && path.startsWith("/api/me/practice/") && method === "POST") {
      const body = request.postDataJSON();
      state.reports.push(body);
      return json({ status: "accepted" });
    }
    if (path.startsWith("/api/me/practice/") && method === "POST") {
      const body = request.postDataJSON();
      state.practiceSubmissions.push(body);
      if (options.failFirstPractice && state.practiceSubmissions.length === 1) {
        return route.abort("failed");
      }
      return json({
        attemptId: body.attemptId,
        mode: body.mode,
        isCorrect: options.practiceCorrect === true,
        correctIndex: 2,
        explanation: "সাবমিটের পরে দেখা যাচাইকৃত পুনরাবৃত্তি ব্যাখ্যা।",
        sourceUrl: "https://ncert.nic.in/example",
      });
    }
    if (path.startsWith("/api/questions/") && path.endsWith("/report") && method === "POST") {
      const body = request.postDataJSON();
      state.reports.push(body);
      return json({ status: "accepted" });
    }
    if (path.startsWith("/api/resources/") && path.endsWith("/feedback") && method === "POST") {
      return json({ accepted: true });
    }
    return json({ detail: `Unhandled deterministic mock: ${method} ${path}` }, 404);
  });

  return state;
}

async function capture(page, testInfo, name) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

async function assertNoHorizontalOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1);
}

async function assertVisibleTouchTargets(page) {
  const tooSmall = await page.evaluate(() =>
    Array.from(document.querySelectorAll("button, a, select"))
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 0 &&
          rect.height > 0
        );
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          label: element.id || element.textContent.trim().slice(0, 40),
          width: rect.width,
          height: rect.height,
        };
      })
      .filter((target) => target.width < 44 || target.height < 44),
  );
  expect(tooSmall).toEqual([]);
}

async function assertBottomNavigationDoesNotCoverContent(page) {
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = "auto";
    window.scrollTo(0, document.documentElement.scrollHeight);
  });
  await page.waitForTimeout(100);
  const geometry = await page.evaluate(() => {
    const navigation = document.querySelector(".bottom-nav, nav.bottom");
    const main = document.querySelector("main");
    if (!navigation || !main) return null;
    const candidates = Array.from(
      main.querySelectorAll("section, article, details, form"),
    ).filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && rect.height > 0;
    });
    const last = candidates.reduce(
      (current, element) =>
        !current || element.getBoundingClientRect().bottom > current.getBoundingClientRect().bottom
          ? element
          : current,
      null,
    );
    return {
      navigationTop: navigation.getBoundingClientRect().top,
      contentBottom: last ? last.getBoundingClientRect().bottom : main.getBoundingClientRect().bottom,
    };
  });
  expect(geometry).not.toBeNull();
  expect(geometry.contentBottom).toBeLessThanOrEqual(geometry.navigationTop + 1);
}

module.exports = {
  ATTEMPT_ONE,
  ATTEMPT_TWO,
  QUIZ_ID,
  assertBottomNavigationDoesNotCoverContent,
  assertNoHorizontalOverflow,
  assertVisibleTouchTargets,
  capture,
  dashboardPayload,
  installApiMocks,
  installTelegramMock,
  preferencesPayload,
  questionId,
  quizPayload,
  resultPayload,
};
