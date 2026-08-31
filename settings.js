(function(){
  "use strict";
  var tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
  var initData=tg&&tg.initData?tg.initData:"";
  var telegramLaunchHash=/(?:^|&)tgWebAppData=/.test(window.location.hash.slice(1))
    ?window.location.hash:"";
  installTelegramNavigation();
  if(tg){try{tg.ready();tg.expand()}catch(e){}}
  var API_BASE=(window.QUIZ_API_BASE||document.querySelector('meta[name="quiz-api-base"]').content||"").replace(/\/$/,"");
  var requestJson=window.miniappRequest;
  var subjects={"history":"ইতিহাস","geography":"ভূগোল","polity":"সংবিধান","economics":"অর্থনীতি","science":"বিজ্ঞান","mathematics":"গণিত","reasoning":"রিজনিং","english":"ইংরেজি","bengali":"বাংলা","computer":"কম্পিউটার","current-affairs":"কারেন্ট অ্যাফেয়ার্স","environment":"পরিবেশ","miscellaneous":"বিবিধ সাধারণ জ্ঞান"};
  var exams={WBCS:"WBCS",WBPSC_CLERKSHIP:"WBPSC Clerkship",WBPSC_MISC:"WBPSC Misc",WBP_CONSTABLE:"WBP Constable",WBP_SI:"WBP SI",KOLKATA_POLICE:"Kolkata Police",PRIMARY_TET:"Primary TET",UPPER_PRIMARY_TET:"Upper Primary TET",SSC:"SSC",RAILWAY:"Railway",BANKING:"Banking"};
  var committedSubjects=[],committedExams=[],savedSnapshot="",activeDialogTrigger=null;

  function el(id){return document.getElementById(id)}
  function api(path){return API_BASE+path}
  function telegramUrl(path){
    var url=new URL(path,window.location.href);
    if(url.origin!==window.location.origin)return url.href;
    if(telegramLaunchHash)url.hash=telegramLaunchHash;
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
  function errorMessage(error){return typeof window.miniappErrorMessage==="function"?window.miniappErrorMessage(error):"এখন তথ্য লোড করা যাচ্ছে না। আবার চেষ্টা করুন।"}
  function localPreference(name,value){try{localStorage.setItem("telegram-quiz-pref:"+name,String(!!value))}catch(e){}}
  function buildChecks(id,items){var box=el(id);Object.keys(items).forEach(function(key){var label=document.createElement("label"),input=document.createElement("input");input.type="checkbox";input.value=key;label.append(input,document.createTextNode(items[key]));box.appendChild(label)})}
  function checkValues(id,values){el(id).querySelectorAll("input").forEach(function(input){input.checked=values.indexOf(input.value)>=0})}
  function checked(id){return Array.from(el(id).querySelectorAll("input:checked")).map(function(input){return input.value})}

  buildChecks("exam-checks",exams);buildChecks("subject-checks",subjects);
  installSelector("subject");installSelector("exam");
  el("open-subject-dialog").addEventListener("click",function(){openSelector("subject")});
  el("subject-dialog-close").addEventListener("click",function(){closeSelector("subject",true)});
  el("subject-clear").addEventListener("click",function(){clearSelector("subject")});
  el("subject-done").addEventListener("click",function(){commitSelector("subject")});
  el("open-exam-dialog").addEventListener("click",function(){openSelector("exam")});
  el("exam-dialog-close").addEventListener("click",function(){closeSelector("exam",true)});
  el("exam-clear").addEventListener("click",function(){clearSelector("exam")});
  el("exam-done").addEventListener("click",function(){commitSelector("exam")});
  el("settings").addEventListener("submit",savePreferences);
  el("settings").addEventListener("input",markDirty);
  el("settings").addEventListener("change",markDirty);
  el("test-sound").addEventListener("click",testSound);
  el("settings-retry").addEventListener("click",loadPreferences);
  el("export-data").addEventListener("click",exportData);
  el("request-deletion").addEventListener("click",showDeletionConfirmation);
  el("confirm-deletion").addEventListener("click",requestDeletion);
  el("cancel-delete-confirm").addEventListener("click",hideDeletionConfirmation);
  el("cancel-deletion").addEventListener("click",cancelDeletion);
  window.addEventListener("beforeunload",function(event){if(!isDirty())return;event.preventDefault();event.returnValue=""});
  if(initData)loadPreferences();
  else showState("নিজের পছন্দ ও গোপনীয়তা দেখতে Telegram-এর কুইজ বাটন থেকে Mini App খুলুন।",false);

  function showState(message,retry){
    el("settings-state").classList.remove("hidden");el("settings-loader").classList.add("hidden");
    el("settings-state-copy").textContent=message;el("settings-retry-wrap").classList.toggle("hidden",!retry);
  }

  function loadPreferences(){
    el("settings").classList.add("hidden");el("settings-state").classList.remove("hidden");el("settings-loader").classList.remove("hidden");
    el("settings-state-copy").textContent="সেটিংস লোড হচ্ছে...";el("settings-retry-wrap").classList.add("hidden");el("settings-retry").disabled=true;
    var slowNotice=window.setTimeout(function(){el("settings-state-copy").textContent="সার্ভার প্রস্তুত হচ্ছে—আর কয়েক সেকেন্ড সময় লাগতে পারে।"},6000);
    requestJson(api("/api/me/preferences"),{headers:{"X-Telegram-Init-Data":initData}}).then(function(prefs){
      fillPreferences(prefs);el("settings-state").classList.add("hidden");el("settings").classList.remove("hidden");
    }).catch(function(error){showState(errorMessage(error),true)}).finally(function(){window.clearTimeout(slowNotice);el("settings-retry").disabled=false});
  }

  function fillPreferences(prefs){
    el("daily-target").value=prefs.dailyQuestionTarget||30;el("language").value="bn";el("quiz-mode").value=prefs.quizMode||"timed";el("difficulty").value=prefs.difficultyPreference||"adaptive";el("display-name").value=prefs.publicDisplayName||"";
    el("leaderboard-visible").checked=prefs.leaderboardVisible!==false;el("username-visible").checked=!!prefs.usernameVisible;el("reminder").checked=false;el("revision-sound").checked=prefs.revisionSoundEnabled!==false;el("revision-vibration").checked=prefs.revisionVibrationEnabled===true;
    committedExams=(prefs.targetExams||[]).filter(function(key){return Object.prototype.hasOwnProperty.call(exams,key)});committedSubjects=(prefs.preferredSubjects||[]).filter(function(key){return Object.prototype.hasOwnProperty.call(subjects,key)});
    localPreference("revisionSoundEnabled",el("revision-sound").checked);localPreference("revisionVibrationEnabled",el("revision-vibration").checked);checkValues("exam-checks",committedExams);checkValues("subject-checks",committedSubjects);updateSelectionSummaries();savedSnapshot=preferenceSnapshot();setDirty(false);
  }

  function selectorConfig(kind){return kind==="subject"?{dialog:"subject-dialog",checks:"subject-checks",count:"subject-dialog-count",open:"open-subject-dialog",close:"subject-dialog-close",clear:"subject-clear",done:"subject-done"}:{dialog:"exam-dialog",checks:"exam-checks",count:"exam-dialog-count",open:"open-exam-dialog",close:"exam-dialog-close",clear:"exam-clear",done:"exam-done"}}
  function selectedFor(kind){return kind==="subject"?committedSubjects:committedExams}
  function setSelectedFor(kind,values){if(kind==="subject")committedSubjects=values;else committedExams=values}
  function bnNumber(value){return String(value).replace(/[0-9]/g,function(d){return"০১২৩৪৫৬৭৮৯"[+d]})}
  function countCopy(count){return bnNumber(count)+"টি নির্বাচিত"}
  function installSelector(kind){
    var config=selectorConfig(kind),dialog=el(config.dialog),checksBox=el(config.checks);
    checksBox.addEventListener("change",function(){updateDialogCount(kind)});
    dialog.addEventListener("cancel",function(event){event.preventDefault();closeSelector(kind,true)});
    dialog.addEventListener("click",function(event){if(event.target===dialog)closeSelector(kind,true)});
    dialog.addEventListener("close",syncDialogState);
  }
  function clearSelector(kind){var config=selectorConfig(kind);el(config.checks).querySelectorAll("input").forEach(function(input){input.checked=false});updateDialogCount(kind)}
  function commitSelector(kind){var config=selectorConfig(kind);setSelectedFor(kind,checked(config.checks));updateSelectionSummaries();closeSelector(kind,true);markDirty()}
  function openSelector(kind){var config=selectorConfig(kind),dialog=el(config.dialog);checkValues(config.checks,selectedFor(kind));updateDialogCount(kind);activeDialogTrigger=el(config.open);if(typeof dialog.showModal==="function")dialog.showModal();else dialog.setAttribute("open","");document.body.classList.add("selector-open");window.requestAnimationFrame(function(){var input=dialog.querySelector("input");(input||el(config.close)).focus()})}
  function closeSelector(kind,restoreFocus){var dialog=el(selectorConfig(kind).dialog);if(!dialog.open)return;if(typeof dialog.close==="function")dialog.close();else dialog.removeAttribute("open");syncDialogState();if(restoreFocus&&activeDialogTrigger)window.requestAnimationFrame(function(){activeDialogTrigger.focus()})}
  function syncDialogState(){if(!document.querySelector(".selector-dialog[open]"))document.body.classList.remove("selector-open")}
  function updateDialogCount(kind){var config=selectorConfig(kind);el(config.count).textContent=countCopy(checked(config.checks).length)}
  function updateSelectionSummaries(){el("subject-summary").textContent=countCopy(committedSubjects.length);el("exam-summary").textContent=committedExams.length?countCopy(committedExams.length):"কোনোটি নয়"}
  function preferenceSnapshot(){return JSON.stringify({targetExams:committedExams.slice().sort(),preferredSubjects:committedSubjects.slice().sort(),dailyQuestionTarget:+el("daily-target").value,preferredLanguage:el("language").value,difficultyPreference:el("difficulty").value,quizMode:el("quiz-mode").value,leaderboardVisible:el("leaderboard-visible").checked,publicDisplayName:el("display-name").value.trim()||null,usernameVisible:el("username-visible").checked,revisionSoundEnabled:el("revision-sound").checked,revisionVibrationEnabled:el("revision-vibration").checked})}
  function isDirty(){return!!savedSnapshot&&preferenceSnapshot()!==savedSnapshot}
  function markDirty(){setDirty(isDirty())}
  function setDirty(dirty){var button=el("settings-submit");button.disabled=!dirty;button.textContent=dirty?"পরিবর্তন সংরক্ষণ করুন":"সব পরিবর্তন সংরক্ষিত";if(!tg)return;try{if(dirty&&typeof tg.enableClosingConfirmation==="function")tg.enableClosingConfirmation();else if(!dirty&&typeof tg.disableClosingConfirmation==="function")tg.disableClosingConfirmation()}catch(e){}}

  function testSound(){
    var message=el("sound-message");message.textContent="শব্দ বাজানো হচ্ছে...";
    try{var AudioCtor=window.AudioContext||window.webkitAudioContext;if(!AudioCtor)throw new Error("unsupported");var context=new AudioCtor(),now=context.currentTime,oscillator=context.createOscillator(),gain=context.createGain();oscillator.type="sine";oscillator.frequency.setValueAtTime(220,now);oscillator.frequency.exponentialRampToValueAtTime(150,now+.16);gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.09,now+.018);gain.gain.exponentialRampToValueAtTime(.0001,now+.17);oscillator.connect(gain);gain.connect(context.destination);oscillator.start(now);oscillator.stop(now+.18);oscillator.onended=function(){context.close();message.textContent="পরীক্ষার শব্দ বাজানো হয়েছে।"}}catch(error){message.textContent="এই ডিভাইসে শব্দ চালু করা যায়নি।"}
  }

  function privacyAction(path){return requestJson(api(path),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData})})}
  function exportData(){var message=el("privacy-message");message.textContent="ডেটা প্রস্তুত হচ্ছে...";privacyAction("/api/me/data-export").then(function(data){var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="quiz-platform-data-export.json";link.click();URL.revokeObjectURL(link.href);message.textContent="ডেটা এক্সপোর্ট তৈরি হয়েছে।"}).catch(function(error){message.textContent=errorMessage(error)})}
  function showDeletionConfirmation(){el("deletion-confirm").classList.remove("hidden");el("request-deletion").setAttribute("aria-expanded","true");el("confirm-deletion").focus()}
  function hideDeletionConfirmation(){el("deletion-confirm").classList.add("hidden");el("request-deletion").setAttribute("aria-expanded","false");el("request-deletion").focus()}
  function requestDeletion(){var message=el("privacy-message"),button=el("confirm-deletion");button.disabled=true;message.textContent="মুছে ফেলার অনুরোধ রাখা হচ্ছে...";privacyAction("/api/me/account-deletion").then(function(result){hideDeletionConfirmation();message.textContent="অনুরোধ রাখা হয়েছে। "+bnNumber(result.gracePeriodDays)+" দিনের মধ্যে চাইলে বাতিল করুন।"}).catch(function(error){message.textContent=errorMessage(error)}).finally(function(){button.disabled=false})}
  function cancelDeletion(){var message=el("privacy-message");privacyAction("/api/me/account-deletion/cancel").then(function(result){message.textContent=result.cancelled?"মুছে ফেলার অনুরোধ বাতিল হয়েছে।":"কোনো সক্রিয় অনুরোধ পাওয়া যায়নি।"}).catch(function(error){message.textContent=errorMessage(error)})}

  function savePreferences(event){
    event.preventDefault();var message=el("settings-message"),button=el("settings-submit");button.disabled=true;message.textContent="সংরক্ষণ হচ্ছে...";
    var sound=el("revision-sound").checked,vibration=el("revision-vibration").checked;
    requestJson(api("/api/me/preferences"),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData,targetExams:committedExams,preferredSubjects:committedSubjects,dailyQuestionTarget:+el("daily-target").value,preferredLanguage:el("language").value,difficultyPreference:el("difficulty").value,quizMode:el("quiz-mode").value,leaderboardVisible:el("leaderboard-visible").checked,publicDisplayName:el("display-name").value.trim()||null,usernameVisible:el("username-visible").checked,dailyReminderEnabled:false,revisionSoundEnabled:sound,revisionVibrationEnabled:vibration})})
      .then(function(){localPreference("revisionSoundEnabled",sound);localPreference("revisionVibrationEnabled",vibration);savedSnapshot=preferenceSnapshot();setDirty(false);message.textContent="সেটিং সংরক্ষিত হয়েছে।"}).catch(function(error){message.textContent=errorMessage(error);setDirty(true)});
  }
})();
