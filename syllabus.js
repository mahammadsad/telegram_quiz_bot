(function(){
  "use strict";
  var apiBase=(document.querySelector('meta[name="quiz-api-base"]')||{}).content||"";
  var fetcher=window.miniappFetch||window.fetch.bind(window);
  var tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
  var initData=tg&&tg.initData?tg.initData:"";
  var payload=null,progress=null,progressByTopic={};
  var requestedExam=(new URLSearchParams(location.search).get("exam")||"").trim().toUpperCase();
  function el(id){return document.getElementById(id)}
  function api(path){return apiBase.replace(/\/$/,"")+path}
  function check(response){if(!response.ok){var error=new Error("request failed");error.status=response.status;throw error}return response.json()}
  function show(id){["loading","error","empty","catalog"].forEach(function(name){el(name).classList.toggle("hidden",name!==id)})}
  function option(value,label){var node=document.createElement("option");node.value=value;node.textContent=label;return node}
  function load(){show("loading");var publicRequest=fetcher(api("/api/syllabus"),{cache:"no-store"}).then(check),progressRequest=initData?fetcher(api("/api/me/syllabus-progress"),{headers:{"X-Telegram-Init-Data":initData},cache:"no-store"}).then(check).catch(function(){return null}):Promise.resolve(null);Promise.all([publicRequest,progressRequest]).then(function(results){payload=results[0];progress=results[1];indexProgress();buildFilters();render();renderProgress()}).catch(function(){show("error")})}
  function indexProgress(){progressByTopic={};if(!progress)return;(progress.subjects||[]).forEach(function(subject){(subject.chapters||[]).forEach(function(chapter){(chapter.microTopics||[]).forEach(function(topic){progressByTopic[topic.key]=topic})})})}
  function buildFilters(){
    var exam=el("exam-filter"),subject=el("subject-filter");exam.length=1;subject.length=1;
    (payload.exams||[]).forEach(function(item){exam.appendChild(option(item.key,item.name))});
    (payload.subjects||[]).forEach(function(item){subject.appendChild(option(item.key,item.name))});
    if((payload.exams||[]).some(function(item){return item.key===requestedExam}))exam.value=requestedExam;
  }
  function metric(value,label){var node=document.createElement("span"),strong=document.createElement("b");strong.textContent=bn(value);node.append(strong,document.createTextNode(label));return node}
  function bn(value){return Number(value||0).toLocaleString("bn-IN")}
  function renderSummary(subjects){
    var chapterCount=0,topicCount=0,available=0,box=el("summary");subjects.forEach(function(subject){chapterCount+=subject.chapterCount||0;topicCount+=subject.microTopicCount||0;available+=subject.availableChapterCount||0});box.textContent="";box.append(metric(subjects.length,"টি বিষয়"),metric(chapterCount,"টি অধ্যায়"),metric(topicCount,"টি মাইক্রো-টপিক"),metric(available,"টি দৈনিক রোটেশনে"));
  }
  function renderProgress(){var card=el("personal-progress");if(!progress){card.classList.add("hidden");return}var summary=progress.summary||{},coverage=Number(summary.coveragePercent)||0,mastery=Number(summary.masteryPercent)||0;el("progress-copy").textContent=bn(summary.attemptedKnowledgePoints)+" / "+bn(summary.mappedKnowledgePoints)+"টি ম্যাপ করা জ্ঞানবিন্দু চেষ্টা করেছেন; "+bn(summary.masteredKnowledgePoints)+"টি আয়ত্ত। "+bn(summary.dueKnowledgePoints)+"টি পুনরাবৃত্তি বাকি।";el("coverage-progress").value=coverage;el("coverage-value").textContent=bn(coverage)+"%";el("mastery-progress").value=mastery;el("mastery-value").textContent=bn(mastery)+"%";card.classList.remove("hidden")}
  function matchesChapter(chapter,query){if(!query)return true;return [chapter.name].concat((chapter.microTopics||[]).map(function(topic){return topic.name})).join(" ").toLowerCase().includes(query)}
  function render(){
    var exam=el("exam-filter").value,subjectKey=el("subject-filter").value,query=el("topic-search").value.trim().toLowerCase(),rows=(payload.subjects||[]).filter(function(subject){return(!exam||subject.examKeys.includes(exam))&&(!subjectKey||subject.key===subjectKey)}).map(function(subject){var copy=Object.assign({},subject);copy.chapters=(subject.chapters||[]).filter(function(chapter){return matchesChapter(chapter,query)});copy.chapterCount=copy.chapters.length;copy.microTopicCount=copy.chapters.reduce(function(total,chapter){return total+(chapter.microTopics||[]).length},0);copy.availableChapterCount=copy.chapters.filter(function(chapter){return chapter.availableInDailyRotation}).length;return copy}).filter(function(subject){return subject.chapters.length});
    renderSummary(rows);var catalog=el("catalog");catalog.textContent="";if(!rows.length){show("empty");return}rows.forEach(function(subject){catalog.appendChild(subjectCard(subject,query))});show("catalog");
  }
  function subjectCard(subject,query){
    var card=document.createElement("article"),head=document.createElement("div"),copy=document.createElement("div"),title=document.createElement("h2"),meta=document.createElement("p"),actions=document.createElement("div"),quiz=document.createElement("a"),practice=document.createElement("a"),chapters=document.createElement("div"),subjectProgress=progressSubject(subject.key);card.className="subject-card";head.className="subject-head";title.textContent=subject.name;meta.textContent=bn(subject.chapterCount)+" অধ্যায় · "+bn(subject.microTopicCount)+" মাইক্রো-টপিক"+(subjectProgress?" · আয়ত্ত "+bn(subjectProgress.masteryPercent)+"%":"");copy.append(title,meta);actions.className="subject-actions";quiz.className="btn primary";quiz.href="./?subject="+encodeURIComponent(subject.key);quiz.textContent="এই বিষয়ের কুইজ";practice.className="btn";practice.href="practice.html?source=weak_topic&subject="+encodeURIComponent(subject.key);practice.textContent="দুর্বল টপিক";actions.append(quiz,practice);head.append(copy,actions);chapters.className="chapter-list";(subject.chapters||[]).forEach(function(chapter){chapters.appendChild(chapterRow(chapter,query))});card.append(head,chapters);return card;
  }
  function progressSubject(key){if(!progress)return null;return(progress.subjects||[]).find(function(subject){return subject.key===key})||null}
  function chapterRow(chapter,query){
    var details=document.createElement("details"),summary=document.createElement("summary"),name=document.createElement("span"),meta=document.createElement("span"),topics=document.createElement("ol");details.className="chapter";name.textContent=chapter.name;meta.className="chapter-meta "+(chapter.availableInDailyRotation?"rotation":"planned");meta.textContent=chapter.availableInDailyRotation?"দৈনিক কুইজে আছে":"সিলেবাসে আছে";summary.append(name,meta);topics.className="topics";(chapter.microTopics||[]).forEach(function(topic){var item=document.createElement("li"),row=document.createElement("span"),topicName=document.createElement("span"),topicProgress=progressByTopic[topic.key];row.className="topic-row";topicName.textContent=topic.name;row.appendChild(topicName);if(topicProgress){var badge=document.createElement("span"),labels={mastered:"আয়ত্ত",in_progress:"চলছে",not_started:"শুরু হয়নি",content_not_mapped:"প্রশ্ন প্রস্তুত নয়"};badge.className="topic-progress "+topicProgress.status.replace("_","-")+(topicProgress.dueKnowledgePoints?" due":"");badge.textContent=(labels[topicProgress.status]||"অগ্রগতি নেই")+(topicProgress.dueKnowledgePoints?" · পুনরাবৃত্তি":"");row.appendChild(badge)}item.appendChild(row);if(query&&topic.name.toLowerCase().includes(query))item.className="match-mark";topics.appendChild(item)});details.open=Boolean(query);details.append(summary,topics);return details;
  }
  ["exam-filter","subject-filter"].forEach(function(id){el(id).addEventListener("change",render)});el("topic-search").addEventListener("input",render);el("clear-filters").addEventListener("click",function(){el("exam-filter").value="";el("subject-filter").value="";el("topic-search").value="";render()});el("retry").addEventListener("click",load);load();
})();
