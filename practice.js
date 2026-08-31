(function(){
  "use strict";
  var tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
  var initData=tg&&tg.initData?tg.initData:"";
  var telegramLaunchHash=/(?:^|&)tgWebAppData=/.test(window.location.hash.slice(1))
    ?window.location.hash:"";
  installTelegramNavigation();
  if(tg){try{tg.ready();tg.expand();}catch(e){}}
  var API_BASE=(window.QUIZ_API_BASE||document.querySelector('meta[name="quiz-api-base"]').content||"").replace(/\/$/,"");
  var params=new URLSearchParams(location.search);
  var requestedSource=params.get("source")||"wrong";
  var subject=params.get("subject")||"";
  if(["wrong","due","bookmark","weak_topic"].indexOf(requestedSource)<0)requestedSource="wrong";
  var launchQuizId=(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.start_param)||"";
  var quizHomeUrl=telegramUrl(launchQuizId?"/?quiz="+encodeURIComponent(launchQuizId):"/");
  var rows=[],index=0,selected=null,started=0,submitting=false,answerFrozen=false;
  var queueMode="",queueSource="",attemptId="",audioContext=null;
  var activeState="loading",slowTimer=null,retryTimer=null,submitRetryTimer=null;
  var feedbackPlayed=Object.create(null);
  var preferences={sound:readLocalPreference("revisionSoundEnabled",true),vibration:readLocalPreference("revisionVibrationEnabled",false)};
  var LETTERS=["A","B","C","D"],BN=["০","১","২","৩","৪","৫","৬","৭","৮","৯"];
  var labels={wrong:["ভুল প্রশ্ন অনুশীলন","সাম্প্রতিক ভুলগুলো আবার চেষ্টা করুন"],due:["আজকের পুনরাবৃত্তি","নির্ধারিত প্রশ্নগুলো মনে করুন"],bookmark:["বুকমার্ক অনুশীলন","সংরক্ষিত প্রশ্নগুলো ঝালিয়ে নিন"],weak_topic:["দুর্বল টপিক","কম দক্ষতার প্রশ্ন অনুশীলন করুন"]};
  var emptyCopy={
    wrong:["এখন কোনো ভুল প্রশ্ন নেই","সাম্প্রতিক কুইজে ভুল হওয়া কোনো প্রশ্ন এখন অনুশীলনের জন্য বাকি নেই। নতুন কুইজ দিয়ে প্রস্তুতি চালিয়ে যান।"],
    due:["আজকের পুনরাবৃত্তি শেষ","আজ নির্ধারিত কোনো প্রশ্ন বাকি নেই। পরবর্তী পুনরাবৃত্তি সময়মতো এখানে দেখা যাবে।"],
    bookmark:["কোনো বুকমার্ক নেই","সংরক্ষিত প্রশ্ন এখনো যোগ করা হয়নি। কুইজের ফল থেকে দরকারি প্রশ্ন বুকমার্ক করুন।"],
    weak_topic:["দুর্বল টপিকের প্রশ্ন নেই","আপনার বর্তমান ফলাফলে আলাদা দুর্বল টপিক পাওয়া যায়নি। নতুন কুইজ দিলে পরিকল্পনা আপডেট হবে।"]
  };

  function el(id){return document.getElementById(id)}
  function bn(v){return String(v).replace(/[0-9]/g,function(d){return BN[+d]})}
  function api(p){return API_BASE+p}
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
  function state(name,moveFocus){
    activeState=name;
    document.body.dataset.screenState=name;
    ["loading","empty","completed","error","practice"].forEach(function(k){el(k).classList.toggle("hidden",k!==name)});
    el("practice-card").setAttribute("aria-busy",name==="loading"?"true":"false");
    if(moveFocus&&name!=="practice")window.requestAnimationFrame(function(){try{el(name).focus()}catch(e){}});
  }
  function setCount(value){el("count").textContent=value===null?"—":bn(value)+(value===0?"":"টি")}
  function request(path,options){
    if(typeof window.miniappRequest!=="function")return Promise.reject({category:"UNKNOWN"});
    return window.miniappRequest(api(path),options||{});
  }
  function categoryOf(error){
    var category=String(error&&error.category||"").toUpperCase().replace(/[ -]+/g,"_");
    if(category)return category;
    var status=Number(error&&error.status||0);
    if(status===401)return initData?"AUTH_EXPIRED":"AUTH_REQUIRED";
    if(status===403)return"AUTH_EXPIRED";
    if(status===429)return"RATE_LIMITED";
    if(status===502||status===503||status===504||status>=500)return"SERVER_TEMPORARY";
    return"UNKNOWN";
  }
  function safeUnknownMessage(error){
    if(typeof window.miniappErrorMessage==="function"){
      try{return window.miniappErrorMessage(error,"অনুশীলন এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।")}catch(e){}
    }
    return"অনুশীলন এখন খোলা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।";
  }
  function safeRequestId(error){
    var value=String(error&&error.requestId||"");
    return/^[A-Za-z0-9._:-]{4,100}$/.test(value)?value:"";
  }
  function clearLoadTimers(){
    if(slowTimer){clearTimeout(slowTimer);slowTimer=null}
    if(retryTimer){clearTimeout(retryTimer);retryTimer=null}
  }
  function showLoadError(error){
    clearLoadTimers();setCount(null);
    var category=categoryOf(error),title="অনুশীলন খোলা যায়নি",message="",showRetry=true,showReopen=false;
    if(category==="AUTH_REQUIRED"){title="Telegram যাচাই প্রয়োজন";message="এই ব্যক্তিগত অনুশীলন দেখতে বটের Mini App বাটন থেকে খুলুন।";showRetry=false;showReopen=true}
    else if(category==="AUTH_EXPIRED"){title="Telegram সেশনের মেয়াদ শেষ";message="নিরাপদভাবে চালিয়ে যেতে বট থেকে Mini App আবার খুলুন।";showRetry=false;showReopen=true}
    else if(category==="OFFLINE"){title="ইন্টারনেট সংযোগ নেই";message="ডিভাইসটি ইন্টারনেটে যুক্ত হলে আবার চেষ্টা করুন।"}
    else if(category==="NETWORK_FAILURE"){title="সংযোগ সম্পন্ন হয়নি";message="নেটওয়ার্ক সংযোগ স্থির হলে আবার চেষ্টা করুন।"}
    else if(category==="REQUEST_TIMEOUT"){title="সাড়া পেতে বেশি সময় লাগছে";message="সার্ভার প্রস্তুত হতে সময় নিচ্ছে। নিরাপদে আবার চেষ্টা করতে পারেন।"}
    else if(category==="RATE_LIMITED"){title="কিছুক্ষণ বিরতি নিন";message="অল্প সময়ে অনেকবার অনুরোধ হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।"}
    else if(category==="SERVER_TEMPORARY"){title="সেবা সাময়িকভাবে ব্যস্ত";message="আপনার তথ্য নিরাপদ আছে। একটু পরে আবার চেষ্টা করুন।"}
    else{message=safeUnknownMessage(error)}
    el("error").dataset.state=category.toLowerCase();el("error-title").textContent=title;el("error-message").textContent=message;
    var requestId=safeRequestId(error),reference=el("error-reference");reference.textContent=requestId?"সহায়তা কোড: "+requestId:"";reference.classList.toggle("hidden",!requestId);
    el("retry").classList.toggle("hidden",!showRetry);el("retry").disabled=false;el("retry").textContent="আবার চেষ্টা করুন";
    el("auth-reopen").classList.toggle("hidden",!showReopen);state("error",true);
    if(category==="RATE_LIMITED")startLoadCooldown(error&&error.retryAfterSeconds);
  }
  function startLoadCooldown(value){
    var remaining=Math.min(300,Math.max(0,Math.ceil(Number(value)||0)));if(!remaining)return;
    var button=el("retry");button.disabled=true;
    function tick(){button.textContent=bn(remaining)+" সেকেন্ড পরে চেষ্টা করুন";if(remaining--<=0){button.disabled=false;button.textContent="আবার চেষ্টা করুন";retryTimer=null;return}retryTimer=setTimeout(tick,1000)}
    tick();
  }
  function readLocalPreference(name,fallback){try{var value=localStorage.getItem("telegram-quiz-pref:"+name);return value===null?fallback:value==="true"}catch(e){return fallback}}
  function writeLocalPreference(name,value){try{localStorage.setItem("telegram-quiz-pref:"+name,String(!!value))}catch(e){}}
  function attemptKey(){return "telegram-practice-attempt:"+(rows[index]&&rows[index].questionId||"unknown")+":"+queueMode}
  function validUuid(value){return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value||"")}
  function newUuid(){
    if(window.crypto&&typeof window.crypto.randomUUID==="function")return window.crypto.randomUUID();
    if(!window.crypto||typeof window.crypto.getRandomValues!=="function")throw new Error("নতুন চেষ্টার নিরাপদ পরিচয় তৈরি করা যায়নি।");
    var bytes=new Uint8Array(16);window.crypto.getRandomValues(bytes);bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    var hex=Array.prototype.map.call(bytes,function(value){return value.toString(16).padStart(2,"0")}).join("");
    return hex.slice(0,8)+"-"+hex.slice(8,12)+"-"+hex.slice(12,16)+"-"+hex.slice(16,20)+"-"+hex.slice(20);
  }
  function savePending(submitted){try{localStorage.setItem(attemptKey(),JSON.stringify({attemptId:attemptId,selectedIndex:selected,submitted:!!submitted}))}catch(e){}}
  function clearPending(){try{localStorage.removeItem(attemptKey())}catch(e){}}
  function restorePending(){
    var pending=null;try{pending=JSON.parse(localStorage.getItem(attemptKey())||"null")}catch(e){}
    if(!pending||!validUuid(pending.attemptId)){attemptId=newUuid();selected=null;answerFrozen=false;savePending(false);return}
    attemptId=pending.attemptId;
    selected=[0,1,2,3].indexOf(pending.selectedIndex)>=0?pending.selectedIndex:null;
    answerFrozen=!!pending.submitted;
  }

  el("title").textContent=labels[requestedSource][0];el("subtitle").textContent=labels[requestedSource][1];
  el("empty-quiz-link").href=quizHomeUrl;el("completed-quiz-link").href=quizHomeUrl;
  var launchUrl=document.querySelector('meta[name="telegram-miniapp-url"]');if(launchUrl)el("auth-reopen").href=launchUrl.content;
  ["due","wrong","bookmark","weak_topic"].forEach(function(source){
    var link=el("source-"+source),active=source===requestedSource;
    link.classList.toggle("active",active);
    if(active)link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");
  });
  el("submit").addEventListener("click",submit);el("next").addEventListener("click",next);el("retry").addEventListener("click",load);
  document.addEventListener("keydown",function(event){if(answerFrozen||submitting)return;if(["1","2","3","4"].indexOf(event.key)>=0){selected=+event.key-1;savePending(false);renderOptions()}else if(event.key==="Enter"&&selected!==null)submit()});
  load();

  function load(){
    clearLoadTimers();setCount(null);el("loading").dataset.state="loading";el("loading-copy").textContent="প্রশ্ন লোড হচ্ছে…";state("loading");
    if(!initData){showLoadError({category:"AUTH_REQUIRED"});return}
    slowTimer=setTimeout(function(){if(activeState==="loading"){el("loading").dataset.state="slow";el("loading-copy").textContent="সার্ভার প্রস্তুত হচ্ছে—আর কয়েক সেকেন্ড সময় লাগতে পারে।"}},3500);
    var path="/api/me/practice-bootstrap?source="+encodeURIComponent(requestedSource)+"&limit=100"+(subject?"&subject="+encodeURIComponent(subject):"");
    request(path,{headers:{"X-Telegram-Init-Data":initData}}).then(function(data){
      clearLoadTimers();
      if(!data||["revision","practice"].indexOf(data.mode)<0||["wrong","due","bookmark","weak_topic"].indexOf(data.sourceType)<0)throw{category:"UNKNOWN"};
      applyPreferences(data.preferences);
      queueMode=data.mode;queueSource=data.sourceType;
      rows=requestedSource==="bookmark"?(Array.isArray(data.questions)?data.questions:[]):(Array.isArray(data.rows)?data.rows:[]);
      if(subject&&requestedSource==="due")rows.sort(function(a,b){return(a.subjectKey===subject?0:1)-(b.subjectKey===subject?0:1)});
      if(queueSource==="weak_topic")rows.sort(function(a,b){return(a.masteryScore||0)-(b.masteryScore||0)});
      setCount(rows.length);
      if(!rows.length){var copy=emptyCopy[requestedSource];el("empty-title").textContent=copy[0];el("empty-message").textContent=copy[1];state("empty",true);return}index=0;render();
    }).catch(showLoadError);
  }
  function applyPreferences(prefs){
    if(!prefs)return;preferences.sound=prefs.revisionSoundEnabled!==false;preferences.vibration=prefs.revisionVibrationEnabled===true;
    writeLocalPreference("revisionSoundEnabled",preferences.sound);writeLocalPreference("revisionVibrationEnabled",preferences.vibration);
  }

  function render(){
    state("practice");submitting=false;started=performance.now();restorePending();
    el("marked").checked=!!rows[index].markedForReview;el("marked").disabled=answerFrozen;
    el("feedback").classList.add("hidden");el("next-wrap").classList.add("hidden");el("submit").parentElement.classList.remove("hidden");
    el("submit").textContent=answerFrozen?"একই উত্তর আবার পাঠান":"উত্তর যাচাই করুন";
    el("position").textContent="প্রশ্ন "+bn(index+1)+" / "+bn(rows.length);el("topic").textContent=rows[index].chapter||rows[index].subjectKey||"";
    el("question").textContent=rows[index].q;el("bar").max=rows.length;el("bar").value=index+1;
    el("next").textContent=index===rows.length-1?(queueMode==="revision"?"পুনরাবৃত্তি শেষ করুন":"অনুশীলন শেষ করুন"):"পরবর্তী প্রশ্ন";
    renderOptions();
  }

  function renderOptions(review){
    var wrap=el("options");wrap.textContent="";(rows[index].o||[]).forEach(function(label,i){
      var button=document.createElement("button");button.type="button";button.className="option"+(selected===i?" selected":"");
      if(review){if(i===review.correctIndex)button.classList.add("correct");else if(i===selected)button.classList.add("wrong")}
      button.disabled=answerFrozen||submitting||!!review;button.setAttribute("aria-pressed",selected===i?"true":"false");
      button.setAttribute("aria-label",LETTERS[i]+". "+label+(review&&i===review.correctIndex?" — সঠিক উত্তর":review&&i===selected?" — আপনার ভুল উত্তর":""));
      button.innerHTML='<span class="key">'+LETTERS[i]+'</span><span></span>';button.lastChild.textContent=label;
      button.addEventListener("click",function(){if(!answerFrozen&&!submitting){selected=i;savePending(false);renderOptions();var current=el("options").children[i];if(current)current.focus()}});wrap.appendChild(button);
    });
    updateSubmitState();
  }
  function updateSubmitState(){el("submit").disabled=selected===null||submitting}

  function primeFeedback(){
    if(queueMode!=="revision"||!preferences.sound)return;
    try{var AudioCtor=window.AudioContext||window.webkitAudioContext;if(!AudioCtor)return;if(!audioContext)audioContext=new AudioCtor();if(audioContext.state==="suspended")audioContext.resume()}catch(e){}
  }
  function revisionMistakeFeedback(result){
    if(result.mode!=="revision"||result.isCorrect||feedbackPlayed[attemptId])return;
    feedbackPlayed[attemptId]=true;
    if(preferences.sound&&audioContext){
      try{var now=audioContext.currentTime,oscillator=audioContext.createOscillator(),gain=audioContext.createGain();oscillator.type="sine";oscillator.frequency.setValueAtTime(220,now);oscillator.frequency.exponentialRampToValueAtTime(150,now+.16);gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.09,now+.018);gain.gain.exponentialRampToValueAtTime(.0001,now+.17);oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start(now);oscillator.stop(now+.18)}catch(e){}
    }
    if(preferences.vibration&&navigator.vibrate){try{navigator.vibrate(70)}catch(e){}}
  }

  function submit(){
    if(submitting||selected===null)return;primeFeedback();submitting=true;answerFrozen=true;savePending(true);renderOptions();el("feedback").classList.add("hidden");
    el("submit").disabled=true;el("submit").textContent="উত্তর যাচাই হচ্ছে...";el("marked").disabled=true;
    var seconds=Math.min(3600,Math.max(0,(performance.now()-started)/1000));
    request("/api/me/practice/"+encodeURIComponent(rows[index].questionId),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData,attemptId:attemptId,selectedIndex:selected,sourceType:queueSource,mode:queueMode,responseTimeSeconds:seconds,markedForReview:el("marked").checked})})
      .then(function(result){
        submitting=false;clearPending();renderOptions(result);revisionMistakeFeedback(result);
        var box=el("feedback");box.className="feedback"+(result.isCorrect?"":" bad");box.textContent="";
        var heading=document.createElement("h2");heading.tabIndex=-1;heading.textContent=result.isCorrect?"সঠিক উত্তর":"উত্তরটি ভুল হয়েছে";box.appendChild(heading);
        if(!result.isCorrect){var correct=document.createElement("p");correct.textContent="সঠিক উত্তর: "+rows[index].o[result.correctIndex];box.appendChild(correct)}
        var explanation=document.createElement("p");explanation.textContent=result.explanation||"ব্যাখ্যা পাওয়া যায়নি।";box.appendChild(explanation);
        if(result.sourceUrl&&/^https:\/\//i.test(result.sourceUrl)){var link=document.createElement("a");link.href=result.sourceUrl;link.target="_blank";link.rel="noopener noreferrer";link.textContent="যাচাই করা উৎস দেখুন";box.appendChild(link)}
        if(result.mode==="revision")appendReportControl(box,rows[index].questionId,attemptId);
        box.classList.remove("hidden");el("submit").parentElement.classList.add("hidden");el("next-wrap").classList.remove("hidden");heading.focus();
      }).catch(showSubmitError);
  }

  function showSubmitError(error){
    submitting=false;if(submitRetryTimer){clearTimeout(submitRetryTimer);submitRetryTimer=null}
    var category=categoryOf(error),box=el("feedback"),heading=document.createElement("h2"),message=document.createElement("p"),retryAllowed=true;
    box.className="feedback bad";box.textContent="";heading.tabIndex=-1;heading.textContent="উত্তর সংরক্ষণ নিশ্চিত হয়নি";
    if(category==="CONFLICT"||Number(error&&error.status)===409){heading.textContent="এই চেষ্টা আর বদলানো যাবে না";message.textContent="এই attempt ID-তে অন্য একটি উত্তর আগে জমা হয়েছে। তালিকাটি আবার খুলে নতুন চেষ্টা শুরু করুন।";retryAllowed=false;el("submit").textContent="নতুন চেষ্টা প্রয়োজন"}
    else if(category==="AUTH_REQUIRED"||category==="AUTH_EXPIRED"){heading.textContent="Telegram সেশন যাচাই করা যায়নি";message.textContent="নিরাপদভাবে উত্তর জমা দিতে বট থেকে Mini App আবার খুলুন। আপনার বাছাই এই ডিভাইসে রাখা আছে।";retryAllowed=false;el("submit").textContent="সেশন আবার খুলুন"}
    else if(category==="OFFLINE"){message.textContent="ইন্টারনেট সংযোগ ফিরলে একই উত্তর আবার পাঠান। একই attempt ID থাকায় নকল চেষ্টা তৈরি হবে না।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    else if(category==="NETWORK_FAILURE"){message.textContent="সংযোগ শেষ হওয়ার আগে ফল নিশ্চিত করা যায়নি। একই উত্তর আবার পাঠালে একই attempt ID ব্যবহার হবে।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    else if(category==="REQUEST_TIMEOUT"){message.textContent="সার্ভারের উত্তর আসতে বেশি সময় লেগেছে। একই উত্তর আবার পাঠালে নকল চেষ্টা তৈরি হবে না।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    else if(category==="RATE_LIMITED"){heading.textContent="কিছুক্ষণ পরে আবার পাঠান";message.textContent="অল্প সময়ে অনেকবার অনুরোধ হয়েছে। আপনার একই উত্তর ও attempt ID রাখা আছে।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    else if(category==="SERVER_TEMPORARY"){message.textContent="সেবা সাময়িকভাবে ব্যস্ত। একই উত্তর আবার পাঠালে একই attempt ID ব্যবহার হবে।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    else{message.textContent="ফল নিশ্চিত করা যায়নি। একই উত্তর আবার পাঠালে একই attempt ID ব্যবহার হবে এবং নকল চেষ্টা তৈরি হবে না।";el("submit").textContent="একই উত্তর আবার পাঠান"}
    var requestId=safeRequestId(error);if(requestId){var reference=document.createElement("p");reference.className="error-reference";reference.textContent="সহায়তা কোড: "+requestId;box.append(heading,message,reference)}else box.append(heading,message);
    box.classList.remove("hidden");renderOptions();el("submit").disabled=!retryAllowed;heading.focus();
    if(category==="RATE_LIMITED"&&retryAllowed)startSubmitCooldown(error&&error.retryAfterSeconds);
  }
  function startSubmitCooldown(value){
    var remaining=Math.min(300,Math.max(0,Math.ceil(Number(value)||0)));if(!remaining)return;
    var button=el("submit");button.disabled=true;
    function tick(){button.textContent=bn(remaining)+" সেকেন্ড পরে একই উত্তর পাঠান";if(remaining--<=0){button.disabled=false;button.textContent="একই উত্তর আবার পাঠান";submitRetryTimer=null;return}submitRetryTimer=setTimeout(tick,1000)}
    tick();
  }

  function appendReportControl(box,questionId,reportAttemptId){
    var details=document.createElement("details"),summary=document.createElement("summary"),fields=document.createElement("div"),reason=document.createElement("select"),notes=document.createElement("textarea"),button=document.createElement("button"),message=document.createElement("p");
    details.className="report";summary.textContent="প্রশ্নটি রিপোর্ট করুন";fields.className="report-fields";reason.className="field";reason.setAttribute("aria-label","রিপোর্টের কারণ");
    [["wrong_answer","সঠিক উত্তর ভুল"],["multiple_correct","একাধিক উত্তর সঠিক"],["ambiguous","প্রশ্ন অস্পষ্ট"],["incorrect_explanation","ব্যাখ্যা ভুল"],["language_spelling","ভাষা বা বানান"],["outdated","তথ্য পুরোনো"],["outside_syllabus","সিলেবাসের বাইরে"],["broken_source","উৎস খোলা যাচ্ছে না"],["duplicate_question","একই প্রশ্ন পুনরাবৃত্তি"],["translation_error","অনুবাদ ভুল"],["other","অন্যান্য"]].forEach(function(item){var option=document.createElement("option");option.value=item[0];option.textContent=item[1];reason.appendChild(option)});
    notes.className="field";notes.maxLength=1000;notes.placeholder="প্রয়োজনে সংক্ষিপ্ত বিবরণ লিখুন";button.type="button";button.className="btn";button.textContent="রিপোর্ট পাঠান";message.className="report-message";message.setAttribute("aria-live","polite");
    button.addEventListener("click",function(){submitPracticeReport(questionId,reportAttemptId,reason,notes,button,message)});fields.append(reason,notes,button,message);details.append(summary,fields);box.appendChild(details);
  }

  function submitPracticeReport(questionId,reportAttemptId,reason,notes,button,message){
    if(button.disabled)return;button.disabled=true;button.textContent="পাঠানো হচ্ছে...";message.textContent="";
    request("/api/me/practice/"+encodeURIComponent(questionId)+"/report",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData,attemptId:reportAttemptId,reason:reason.value,details:notes.value})})
      .then(function(){message.textContent="রিপোর্ট গ্রহণ করা হয়েছে। ধন্যবাদ।";button.textContent="রিপোর্ট পাঠানো হয়েছে"})
      .catch(function(error){button.disabled=false;button.textContent="আবার রিপোর্ট পাঠান";message.textContent=error.status===409?"এই পুনরাবৃত্তি থেকে প্রশ্নটি আগে রিপোর্ট করা হয়েছে।":"রিপোর্ট পাঠানো যায়নি। আবার চেষ্টা করুন।"});
  }

  function next(){
    if(index<rows.length-1){index++;render();el("question").focus()}
    else{
      el("completed-title").textContent=queueMode==="revision"?"আজকের পুনরাবৃত্তি সম্পন্ন":"অনুশীলন সম্পন্ন";
      el("completed-message").textContent=queueMode==="revision"?"আপনার উত্তরগুলো সংরক্ষিত হয়েছে এবং পরবর্তী পুনরাবৃত্তির সময়সূচি আপডেট হয়েছে।":"আপনার উত্তর ও অগ্রগতি সফলভাবে সংরক্ষিত হয়েছে।";
      el("completed-count").textContent=bn(rows.length);state("completed",true);
    }
  }
})();
