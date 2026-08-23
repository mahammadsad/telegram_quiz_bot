(function(){
  "use strict";
  var tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
  var initData=tg&&tg.initData?tg.initData:"";
  var telegramLaunchHash=/(?:^|&)tgWebAppData=/.test(window.location.hash.slice(1))
    ?window.location.hash:"";
  installTelegramNavigation();
  if(tg){try{tg.ready();tg.expand()}catch(e){}}
  var API_BASE=(window.QUIZ_API_BASE||document.querySelector('meta[name="quiz-api-base"]').content||"").replace(/\/$/,"");
  var BN=["০","১","২","৩","৪","৫","৬","৭","৮","৯"];
  var queryParams=new URLSearchParams(location.search);
  var quizId=queryParams.get("quiz")||"";
  var requestedSection=queryParams.get("section")||"";
  var launchQuizId=quizId||(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.start_param)||"";
  var quizHomeUrl=telegramUrl(launchQuizId?"/?quiz="+encodeURIComponent(launchQuizId):"/");
  var boardLoading=false,boardOffset=0,boardLimit=20,boardParticipants=0,dashboardData=null;
  var subjects={"history":"ইতিহাস","geography":"ভূগোল","polity":"সংবিধান","economics":"অর্থনীতি","science":"বিজ্ঞান","mathematics":"গণিত","reasoning":"রিজনিং","english":"ইংরেজি","bengali":"বাংলা","computer":"কম্পিউটার","current-affairs":"কারেন্ট অ্যাফেয়ার্স","environment":"পরিবেশ","miscellaneous":"বিবিধ সাধারণ জ্ঞান"};

  function el(id){return document.getElementById(id)}
  function bn(value){return String(value).replace(/[0-9]/g,function(digit){return BN[+digit]})}
  function api(path){return API_BASE+path}
  function telegramUrl(path){
    var url=new URL(path,window.location.href);
    if(url.origin!==window.location.origin)return url.href;
    if(telegramLaunchHash){
      if(url.hash&&url.hash!==telegramLaunchHash){
        var section=url.hash.slice(1);
        if(/^[A-Za-z0-9_-]+$/.test(section))url.searchParams.set("section",section);
      }
      url.hash=telegramLaunchHash;
    }
    return url.pathname+url.search+url.hash;
  }
  function navigateTelegram(path){window.location.href=telegramUrl(path)}
  function installTelegramNavigation(){
    if(!telegramLaunchHash)return;
    document.addEventListener("click",function(event){
      if(event.defaultPrevented||(event.button!==undefined&&event.button!==0)||
          event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      var link=event.target.closest?event.target.closest("a[href]"):null;
      if(!link||link.target==="_blank"||link.hasAttribute("download"))return;
      var url=new URL(link.getAttribute("href"),window.location.href);
      if(url.origin!==window.location.origin)return;
      event.preventDefault();navigateTelegram(link.getAttribute("href"));
    });
  }
  function authHeaders(){return initData?{"X-Telegram-Init-Data":initData}:{}}
  function check(response){return response.ok?response.json():response.json().catch(function(){return{}}).then(function(body){var error=new Error(body.detail||String(response.status));error.status=response.status;throw error})}

  buildOptions();syncSubject();
  el("board-load").addEventListener("click",function(){boardOffset=0;loadBoard()});
  el("board-type").addEventListener("change",function(){boardOffset=0;syncSubject()});
  el("board-subject").addEventListener("change",function(){boardOffset=0});
  el("board-prev").addEventListener("click",function(){if(boardOffset>0){boardOffset=Math.max(0,boardOffset-boardLimit);loadBoard()}});
  el("board-next").addEventListener("click",function(){if(boardOffset+boardLimit<boardParticipants){boardOffset+=boardLimit;loadBoard()}});
  el("performance-subject").addEventListener("change",function(){buildPerformanceChapters();applyPerformanceFilters()});
  el("performance-chapter").addEventListener("change",applyPerformanceFilters);
  el("performance-days").addEventListener("change",applyPerformanceFilters);
  el("performance-reset").addEventListener("click",resetPerformanceFilters);
  el("personal-retry").addEventListener("click",loadPersonal);
  el("page-link").href=quizHomeUrl;
  if(quizId){el("page-kicker").textContent="এই কুইজের ফলাফল";el("page-title").textContent="কুইজ ড্যাশবোর্ড";el("page-link").href="dashboard.html";el("page-link").textContent="আমার ড্যাশবোর্ড";el("board-title").textContent="এই কুইজের র‍্যাঙ্কিং";el("board-controls").classList.add("hidden")}
  loadBoard();
  if(quizId)showContent();
  else if(initData)loadPersonal();
  else{showContent();showPersonalState("নিজের অগ্রগতি দেখতে Telegram-এর কুইজ বাটন থেকে Mini App খুলুন।",false)}

  function showContent(){
    el("loading").classList.add("hidden");el("content").classList.remove("hidden");
    if(requestedSection==="analytics"){
      window.requestAnimationFrame(function(){el("analytics").scrollIntoView({block:"start"})});
    }
  }

  function showPersonalState(message,retry){el("personal-state-copy").textContent=message;el("personal-state").classList.remove("hidden");el("personal-retry").classList.toggle("hidden",!retry)}

  function loadPersonal(){el("personal-retry").disabled=true;showPersonalState("আপনার ড্যাশবোর্ড লোড হচ্ছে...",false);
    miniappFetch(api("/api/me/dashboard"),{headers:authHeaders()}).then(check).then(function(data){el("personal-state").classList.add("hidden");renderPersonal(data);showContent()}).catch(function(){showContent();showPersonalState("ড্যাশবোর্ডের তথ্য এখন লোড করা যাচ্ছে না। ইন্টারনেট দেখে আবার চেষ্টা করুন।",true)}).finally(function(){el("personal-retry").disabled=false})}

  function renderPersonal(data){
    ["identity-card","personal","personal-metrics","performance-filters","activity-card","subjects-card","weak-card","mastery-card","chapters-card","insights-card","recent-card","next-card"].forEach(function(id){el(id).classList.remove("hidden")});
    renderIdentity(data);
    var target=data.dailyTarget||30,today=data.todayAnswered||0,pct=Math.min(100,Math.round(today/target*100));
    var due=data.revisionDueToday===undefined?(data.dueReviews||0):data.revisionDueToday;
    el("goal-copy").textContent=bn(today)+" / "+bn(target);
    el("goal-note").textContent=pct>=100?"আজকের লক্ষ্য পূর্ণ হয়েছে—এখন পুনরাবৃত্তি করুন।":"আর "+bn(Math.max(0,target-today))+"টি প্রশ্ন বাকি।";
    el("goal-bar").value=pct;
    el("m-accuracy").textContent=bn(data.accuracy||0)+"%";el("m-answered").textContent=bn(data.totalAnswered||0);el("m-due").textContent=bn(due);
    el("m-streak").textContent=bn(data.currentStreak||0)+" দিন";el("m-longest").textContent=bn(data.longestStreak||0)+" দিন";el("m-improvement").textContent=bn(data.averageImprovement||0)+"%";
    dashboardData=data;buildPerformanceChapters();applyPerformanceFilters();
    var weakSubject=data.weakestSubject&&data.weakestSubject.subjectKey;
    el("weak-practice").href=weakSubject?"practice.html?source=weak_topic&subject="+encodeURIComponent(weakSubject):"practice.html?source=wrong";
    el("mastery-copy").textContent=bn(data.revisionMastered||0)+" / "+bn(data.revisionTotal||0)+"টি প্রশ্ন আয়ত্ত হয়েছে";
    el("mastery-bar").value=Math.min(100,data.revisionCompletion||0);
    el("r-due").textContent=bn(due);el("r-overdue").textContent=bn(data.overdueQuestions||0);el("r-weak").textContent=bn(data.weakQuestions||0);el("r-mastered").textContent=bn(data.recentlyMastered||0);
    renderRevisionSubjects(data.subjectRevisionCounts||[]);
    el("x-response").textContent=data.averageResponseTimeSeconds===null||data.averageResponseTimeSeconds===undefined?"—":bn(Math.round(data.averageResponseTimeSeconds))+" সেকেন্ড";
    el("x-bookmarks").textContent=bn(data.bookmarkedQuestions||0);el("x-reports").textContent=bn(data.questionsReported||0);
    var strong=(data.strongestTopics||[])[0];el("x-strong").textContent=strong?(strong.chapter||strong.microTopicKey||"—"):"—";
    renderNextAction(data,due,weakSubject);
  }

  function renderIdentity(data){
    var identity=data.identity||{},avatar=el("identity-avatar");avatar.textContent="";
    if(identity.profilePhotoUrl&&/^https:\/\//i.test(identity.profilePhotoUrl)){var image=document.createElement("img");image.src=identity.profilePhotoUrl;image.alt="আপনার Telegram প্রোফাইল ছবি";avatar.appendChild(image)}else avatar.textContent=identity.initials||"আ";
    el("identity-name").textContent=identity.displayName||"শিক্ষার্থী";el("identity-username").textContent=identity.username||"";el("identity-label").textContent=identity.label||"এটি আপনার ড্যাশবোর্ড";
    var due=data.revisionDueToday===undefined?(data.dueReviews||0):data.revisionDueToday;
    el("i-attempted").textContent=bn(data.totalAnswered||0);el("i-correct").textContent=bn(data.correctAnswers||0);el("i-incorrect").textContent=bn(data.incorrectAnswers||0);el("i-accuracy").textContent=bn(data.accuracy||0)+"%";
    el("i-streak").textContent=bn(data.currentStreak||0)+" দিন";el("i-best-streak").textContent=bn(data.longestStreak||0)+" দিন";el("i-quizzes").textContent=bn(data.totalQuizzesCompleted||0);
    el("i-overall-rank").textContent=data.currentOverallRank?"#"+bn(data.currentOverallRank):"—";el("i-weekly-rank").textContent=data.weeklyRank?"#"+bn(data.weeklyRank):"—";el("i-due").textContent=bn(due);
    var strongest=data.strongestSubject,weakest=data.weakestSubject,parts=[];
    if(strongest)parts.push("সবচেয়ে শক্তিশালী: "+(subjects[strongest.subjectKey]||strongest.subjectKey)+" ("+bn(strongest.accuracy||0)+"%)");
    if(weakest)parts.push("আরও অনুশীলন দরকার: "+(subjects[weakest.subjectKey]||weakest.subjectKey)+" ("+bn(weakest.accuracy||0)+"%)");
    parts.push("মেয়াদ পেরোনো প্রশ্ন: "+bn(data.overdueQuestions||0));el("identity-strengths").textContent=parts.join(" · ");
  }

  function resetPerformanceFilters(){
    el("performance-subject").value="";el("performance-days").value="30";buildPerformanceChapters();applyPerformanceFilters();
  }

  function buildPerformanceChapters(){
    var select=el("performance-chapter"),subject=el("performance-subject").value,current=select.value,names=[];select.textContent="";
    var all=document.createElement("option");all.value="";all.textContent="সব অধ্যায়";select.appendChild(all);
    if(subject&&dashboardData){(dashboardData.chapterPerformance||[]).forEach(function(row){if(row.subjectKey===subject&&row.chapter&&names.indexOf(row.chapter)<0)names.push(row.chapter)})}
    names.sort(function(a,b){return a.localeCompare(b,"bn")}).forEach(function(name){var option=document.createElement("option");option.value=name;option.textContent=name;select.appendChild(option)});
    select.disabled=!subject;if(subject&&names.indexOf(current)>=0)select.value=current;
  }

  function applyPerformanceFilters(){
    if(!dashboardData)return;
    var subject=el("performance-subject").value,chapter=el("performance-chapter").value,days=Number(el("performance-days").value)||30;
    function subjectMatch(row){return!subject||row.subjectKey===subject}
    function chapterMatch(row){return!chapter||row.chapter===chapter}
    var activity=(dashboardData.progressOverTime||[]).slice(-days);
    var subjectRows=(dashboardData.subjectPerformance||[]).filter(subjectMatch);
    var weakRows=(dashboardData.weakestTopics||[]).filter(function(row){return subjectMatch(row)&&chapterMatch(row)});
    var chapterRows=(dashboardData.chapterPerformance||[]).filter(function(row){return subjectMatch(row)&&chapterMatch(row)});
    var recent=(dashboardData.recentQuizzes||[]).filter(function(row){return(!subject||quizSubject(row.quizId)===subject)&&withinDays(row.completedAt,days)});
    el("activity-title").textContent=bn(days)+" দিনের অগ্রগতি";renderActivity(activity);
    renderBars("subjects",subjectRows,function(row){return subjects[row.subjectKey]||row.subjectKey},"accuracy");
    renderBars("weak",weakRows,function(row){return row.chapter||row.microTopicKey},"accuracy");
    renderBars("chapters",chapterRows,function(row){return row.chapter||"অধ্যায়"},"accuracy");renderRecentQuizzes(recent);
    var scope=subject?(subjects[subject]||subject):"সব বিষয়";if(chapter)scope+=" · "+chapter;
    el("performance-filter-message").textContent="দৈনিক অগ্রগতি ও সাম্প্রতিক কুইজ: গত "+bn(days)+" দিন · বিষয় ও অধ্যায়: "+scope;
  }

  function withinDays(value,days){var timestamp=Date.parse(value||"");return Number.isNaN(timestamp)||timestamp>=Date.now()-days*86400000}

  function renderActivity(rows){
    var box=el("activity"),max=Math.max.apply(null,[1].concat(rows.map(function(row){return row.answered||0})));box.textContent="";box.className="activity";
    if(!rows.length){box.textContent="এখনও দৈনিক অগ্রগতির তথ্য নেই।";box.className="muted";return}
    rows.forEach(function(row){var bar=document.createElement("span"),svg=document.createElementNS("http://www.w3.org/2000/svg","svg"),track=document.createElementNS("http://www.w3.org/2000/svg","rect"),fill=document.createElementNS("http://www.w3.org/2000/svg","rect");bar.className="day";bar.dataset.label=row.date+": "+bn(row.answered||0)+"টি";bar.setAttribute("aria-hidden","true");svg.setAttribute("viewBox","0 0 100 10");svg.setAttribute("preserveAspectRatio","none");track.setAttribute("class","day-track");track.setAttribute("width","100");track.setAttribute("height","10");fill.setAttribute("class","day-value");fill.setAttribute("width",String(Math.max(0,Math.min(100,(row.answered||0)/max*100))));fill.setAttribute("height","10");svg.append(track,fill);bar.appendChild(svg);box.appendChild(bar)});
  }

  function renderBars(id,rows,label,value){
    var box=el(id);box.textContent="";box.className="bars";
    if(!rows.length){box.textContent="এখনও যথেষ্ট তথ্য নেই।";box.className="muted";return}
    rows.slice(0,8).forEach(function(item){var row=document.createElement("div"),name=document.createElement("b"),bar=document.createElement("progress"),number=document.createElement("span");row.className="bar-row";name.textContent=label(item);bar.className="bar";bar.max=100;bar.value=Math.min(100,item[value]||0);number.textContent=bn(item[value]||0)+"%";row.append(name,bar,number);box.appendChild(row)});
  }

  function renderRevisionSubjects(rows){var box=el("revision-subjects");box.textContent="";if(!rows.length){box.textContent="বিষয়ভিত্তিক বাকি প্রশ্ন নেই।";box.className="muted";return}box.className="bars";var max=Math.max.apply(null,rows.map(function(row){return row.due||0}));rows.forEach(function(item){var row=document.createElement("div"),name=document.createElement("b"),bar=document.createElement("progress"),number=document.createElement("span");row.className="bar-row";name.textContent=subjects[item.subjectKey]||item.subjectKey;bar.className="bar";bar.max=Math.max(1,max);bar.value=item.due||0;number.textContent=bn(item.due||0)+"টি";row.append(name,bar,number);box.appendChild(row)})}

  function renderRecentQuizzes(rows){var box=el("recent-quizzes");box.textContent="";if(!rows.length){box.textContent="এখনও কোনো সম্পন্ন কুইজ নেই। প্রথম কুইজটি শেষ করলে এখানে ফল দেখা যাবে।";box.className="muted";return}box.className="recent-list";rows.forEach(function(item){var link=document.createElement("a"),copy=document.createElement("div"),title=document.createElement("b"),meta=document.createElement("small"),score=document.createElement("div"),net=item.netScore===undefined?item.score:item.netScore;link.className="recent-item";link.href="dashboard.html?quiz="+encodeURIComponent(item.quizId);title.textContent=quizLabel(item.quizId);meta.textContent=formatDate(item.completedAt)+" · চেষ্টা "+bn(item.attemptNumber||1)+" · "+formatDuration(item.durationSeconds);score.className="recent-score";score.textContent=bn(net||0)+"/"+bn(item.total||10);copy.append(title,meta);link.append(copy,score);box.appendChild(link)})}

  function renderNextAction(data,due,weakSubject){var copy=el("next-copy"),link=el("next-link");if((data.overdueQuestions||0)>0){copy.textContent=bn(data.overdueQuestions)+"টি মেয়াদ-পেরোনো প্রশ্ন আগে ঝালিয়ে নিন।";link.href="practice.html?source=due";link.textContent="পুনরাবৃত্তি শুরু করুন"}else if(due>0){copy.textContent="আজকের জন্য "+bn(due)+"টি প্রশ্ন পুনরাবৃত্তি বাকি।";link.href="practice.html?source=due";link.textContent="পুনরাবৃত্তি শুরু করুন"}else if((data.weakQuestions||0)>0){copy.textContent="দুর্বল টপিক থেকে কয়েকটি প্রশ্ন অনুশীলন করুন।";link.href=weakSubject?"practice.html?source=weak_topic&subject="+encodeURIComponent(weakSubject):"practice.html?source=wrong";link.textContent="দুর্বল টপিক অনুশীলন"}else{copy.textContent="আজকের লক্ষ্য ধরে রাখতে একটি কুইজ দিন।";link.href=quizHomeUrl;link.textContent="কুইজ খুলুন"}}

  function quizSubject(quizId){var parts=String(quizId||"").split("-");return parts.length<2?"":parts.slice(1).join("-")}
  function quizLabel(quizId){var key=quizSubject(quizId);return key?(subjects[key]||key)+" কুইজ":"কুইজ"}
  function formatDate(value){if(!value)return"তারিখ নেই";try{return new Intl.DateTimeFormat("bn-IN",{timeZone:"Asia/Kolkata",day:"numeric",month:"short",year:"numeric"}).format(new Date(value))}catch(e){return String(value).slice(0,10)}}

  function loadBoard(){
    if(boardLoading)return;boardLoading=true;el("board-load").disabled=true;el("board-load").textContent="লোড হচ্ছে...";updateBoardPager();
    var type=el("board-type").value,subject=el("board-subject").value;
    var path=quizId?"/api/quiz/"+encodeURIComponent(quizId)+"/leaderboard?limit=10&offset=0":"/api/leaderboards/"+type+"?limit="+boardLimit+"&offset="+boardOffset+(type==="subject_accuracy"?"&subject="+encodeURIComponent(subject):"");
    path+="&privacyRelease=20260801045552";
    el("board").classList.add("hidden");el("your-rank").classList.add("hidden");el("board-state").classList.remove("hidden");el("board-state").textContent="তালিকা লোড হচ্ছে...";
    miniappFetch(api(path),{headers:authHeaders(),cache:"no-store"}).then(check).then(renderBoard).catch(function(){el("board-state").textContent="র‍্যাঙ্কিং এখন পাওয়া যাচ্ছে না। আবার চেষ্টা করুন।"}).finally(function(){boardLoading=false;el("board-load").disabled=false;el("board-load").textContent="দেখুন";updateBoardPager()});
  }

  function renderBoard(data){
    var rows=data.rows||[],current=data.currentUser||null,box=el("board");box.textContent="";
    if(quizId&&current)renderRankSummary(current);else el("your-rank").classList.add("hidden");
    rows.forEach(function(row){box.appendChild(boardRow(data,row))});
    var currentVisible=rows.some(function(row){return row.isCurrentUser===true});
    if(current&&!currentVisible&&data.separatorRequired){var separator=document.createElement("div");separator.className="separator";separator.textContent="•••";separator.setAttribute("aria-label","মাঝের র‍্যাঙ্কগুলো সংক্ষিপ্ত করা হয়েছে");box.appendChild(separator);box.appendChild(boardRow(data,current))}
    var hasRows=rows.length>0||!!current;el("board-state").classList.toggle("hidden",hasRows);el("board-state").textContent=hasRows?"":"এখনও পর্যাপ্ত ফলাফল নেই।";box.classList.toggle("hidden",!hasRows);
    var negative=!!(data.markingScheme&&data.markingScheme.negativeMarking);el("tie-break").textContent=quizId?(negative?"প্রথম চেষ্টার নেট স্কোর, বেশি সঠিক, কম ভুল, কম সময়, তারপর আগে শেষ করার ক্রমে র‍্যাঙ্ক নির্ধারিত হয়।":"প্রথম চেষ্টার স্কোর, উত্তর দেওয়া প্রশ্ন, কম সময়, তারপর আগে শেষ করার ক্রমে র‍্যাঙ্ক নির্ধারিত হয়।"):"এই তালিকার হিসাব সার্ভারে নির্ধারিত নিয়মে করা হয়।";if(quizId)el("rank-help").textContent=negative?"কুইজ র‍্যাঙ্কে প্রথম চেষ্টার নেট স্কোর আগে দেখা হয়। প্রতিটি ভুল উত্তরে ০.২৫ নম্বর কাটা হয়; উত্তর না দিলে নম্বর কাটে না। নেট স্কোর সমান হলে বেশি সঠিক উত্তর, কম ভুল, কম সময়, তারপর আগে সম্পন্ন করা চেষ্টা এগিয়ে থাকে। পুনরায় চেষ্টা ও অনুশীলন মূল কুইজ র‍্যাঙ্ক বদলায় না।":"এই ঐতিহাসিক কুইজে নেগেটিভ মার্কিং ছিল না। প্রথম চেষ্টার সঠিক স্কোর আগে দেখা হয়; সমান হলে বেশি উত্তর, কম সময়, তারপর আগে সম্পন্ন করা চেষ্টা এগিয়ে থাকে।";
    updateBoardPager(data);
  }

  function updateBoardPager(data){
    var pager=el("board-pager");if(quizId){pager.classList.add("hidden");return}
    if(data){boardParticipants=Math.max(0,Number(data.participants)||0);if(Number.isFinite(Number(data.offset)))boardOffset=Math.max(0,Number(data.offset))}
    var start=boardParticipants?boardOffset+1:0,end=Math.min(boardOffset+boardLimit,boardParticipants);
    el("board-page").textContent=boardParticipants?bn(start)+"–"+bn(end)+" / "+bn(boardParticipants):"কোনো ফল নেই";
    el("board-prev").disabled=boardLoading||boardOffset<=0;el("board-next").disabled=boardLoading||boardOffset+boardLimit>=boardParticipants;pager.classList.remove("hidden");
  }

  function boardRow(data,item){
    var row=document.createElement("article"),rank=document.createElement("div"),who=document.createElement("div"),name=document.createElement("div"),meta=document.createElement("div"),value=document.createElement("div");
    row.className="row"+(item.isCurrentUser?" me":"");rank.className="rank";rank.textContent=bn(item.rank||"—");name.className="name";
    var initials=document.createElement("span");initials.className="mini-avatar";initials.textContent=item.initials||"শি";initials.setAttribute("aria-hidden","true");name.appendChild(initials);
    name.appendChild(document.createTextNode(item.displayName||item.display_name||"শিক্ষার্থী"));
    if(item.isCurrentUser){var badge=document.createElement("span");badge.className="you";badge.textContent="আপনি";name.appendChild(badge)}
    meta.className="meta";meta.textContent=quizId?"সঠিকতা "+bn(item.accuracy||0)+"% · "+formatDuration(item.durationSeconds):bn(item.total_answered||item.totalAnswered||0)+"টি উত্তর";
    value.className="value";value.textContent=quizId?bn(item.netScore===undefined?(item.score||0):item.netScore)+"/"+bn(item.total||10):boardValue(data.type,item);who.append(name,meta);row.append(rank,who,value);return row;
  }

  function renderRankSummary(current){
    var box=el("your-rank");box.textContent="";var heading=document.createElement("h3");heading.textContent="আপনার র‍্যাঙ্ক";box.appendChild(heading);
    [["র‍্যাঙ্ক","#"+bn(current.rank||"—")],["নেট স্কোর",bn(current.netScore===undefined?(current.score||0):current.netScore)+"/"+bn(current.total||10)],["কাটা নম্বর","−"+bn(current.negativeMarks||0)],["সঠিকতা",bn(current.accuracy||0)+"%"],["সঠিক / ভুল",bn(current.correct||0)+" / "+bn(current.incorrect||0)],["উত্তর দেওয়া হয়নি",bn(current.unanswered||0)],["সময়",formatDuration(current.durationSeconds)],["পার্সেন্টাইল",bn(current.percentile||0)+"%"],["র‍্যাঙ্ক পরিবর্তন",formatRankMovement(current.rankMovement)]].forEach(function(metric){var wrap=document.createElement("div"),label=document.createElement("b"),value=document.createElement("span");label.textContent=metric[0];value.textContent=metric[1];wrap.append(label,value);box.appendChild(wrap)});box.classList.remove("hidden");
  }

  function formatDuration(seconds){if(seconds===null||seconds===undefined)return"সময় নেই";var value=Math.max(0,Math.round(seconds));return bn(Math.floor(value/60))+":"+bn(String(value%60).padStart(2,"0"))}
  function formatRankMovement(value){if(value===null||value===undefined)return"তথ্য নেই";var movement=Number(value)||0;return movement===0?"অপরিবর্তিত":movement>0?"↑ "+bn(movement):"↓ "+bn(Math.abs(movement))}
  function boardValue(type,item){if(type==="consistency")return bn(item.value||0)+" দিন";if(type==="improvement")return "+"+bn(item.value||0)+"%";if(type==="overall_rank")return bn(item.value||0)+" সঠিক";return bn(item.value||0)+"%"}
  function syncSubject(){el("board-subject").classList.toggle("hidden",el("board-type").value!=="subject_accuracy")}
  function buildOptions(){Object.keys(subjects).forEach(function(key){["board-subject","performance-subject"].forEach(function(id){var option=document.createElement("option");option.value=key;option.textContent=subjects[key];el(id).appendChild(option)})})}
})();
