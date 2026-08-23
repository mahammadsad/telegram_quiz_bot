(function(){
  "use strict";
  var tg=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
  var initData=tg&&tg.initData?tg.initData:"";
  var telegramLaunchHash=/(?:^|&)tgWebAppData=/.test(window.location.hash.slice(1))
    ?window.location.hash:"";
  installTelegramNavigation();
  if(tg){try{tg.ready();tg.expand()}catch(e){}}
  var API_BASE=(window.QUIZ_API_BASE||document.querySelector('meta[name="quiz-api-base"]').content||"").replace(/\/$/,"");
  var subjects={"history":"ইতিহাস","geography":"ভূগোল","polity":"সংবিধান","economics":"অর্থনীতি","science":"বিজ্ঞান","mathematics":"গণিত","reasoning":"রিজনিং","english":"ইংরেজি","bengali":"বাংলা","computer":"কম্পিউটার","current-affairs":"কারেন্ট অ্যাফেয়ার্স","environment":"পরিবেশ","miscellaneous":"বিবিধ সাধারণ জ্ঞান"};
  var exams={WBCS:"WBCS",WBPSC_CLERKSHIP:"WBPSC Clerkship",WBPSC_MISC:"WBPSC Misc",WBP_CONSTABLE:"WBP Constable",WBP_SI:"WBP SI",KOLKATA_POLICE:"Kolkata Police",PRIMARY_TET:"Primary TET",UPPER_PRIMARY_TET:"Upper Primary TET",SSC:"SSC",RAILWAY:"Railway",BANKING:"Banking"};

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
  function check(response){return response.ok?response.json():response.json().catch(function(){return{}}).then(function(body){var error=new Error(body.detail||String(response.status));error.status=response.status;throw error})}
  function localPreference(name,value){try{localStorage.setItem("telegram-quiz-pref:"+name,String(!!value))}catch(e){}}
  function buildChecks(id,items){var box=el(id);Object.keys(items).forEach(function(key){var label=document.createElement("label"),input=document.createElement("input");input.type="checkbox";input.value=key;label.append(input,document.createTextNode(items[key]));box.appendChild(label)})}
  function checkValues(id,values){el(id).querySelectorAll("input").forEach(function(input){input.checked=values.indexOf(input.value)>=0})}
  function checked(id){return Array.from(el(id).querySelectorAll("input:checked")).map(function(input){return input.value})}

  buildChecks("exam-checks",exams);buildChecks("subject-checks",subjects);
  el("settings").addEventListener("submit",savePreferences);
  el("test-sound").addEventListener("click",testSound);
  el("settings-retry").addEventListener("click",loadPreferences);
  el("export-data").addEventListener("click",exportData);
  el("request-deletion").addEventListener("click",requestDeletion);
  el("cancel-deletion").addEventListener("click",cancelDeletion);
  if(initData)loadPreferences();
  else showState("নিজের পছন্দ ও গোপনীয়তা দেখতে Telegram-এর কুইজ বাটন থেকে Mini App খুলুন।",false);

  function showState(message,retry){
    el("settings-state").classList.remove("hidden");el("settings-loader").classList.add("hidden");
    el("settings-state-copy").textContent=message;el("settings-retry-wrap").classList.toggle("hidden",!retry);
  }

  function loadPreferences(){
    el("settings").classList.add("hidden");el("settings-state").classList.remove("hidden");el("settings-loader").classList.remove("hidden");
    el("settings-state-copy").textContent="সেটিংস লোড হচ্ছে...";el("settings-retry-wrap").classList.add("hidden");el("settings-retry").disabled=true;
    miniappFetch(api("/api/me/preferences"),{headers:{"X-Telegram-Init-Data":initData}}).then(check).then(function(prefs){
      fillPreferences(prefs);el("settings-state").classList.add("hidden");el("settings").classList.remove("hidden");
    }).catch(function(){showState("সেটিংস এখন লোড করা যাচ্ছে না। ইন্টারনেট দেখে আবার চেষ্টা করুন।",true)}).finally(function(){el("settings-retry").disabled=false});
  }

  function fillPreferences(prefs){
    el("daily-target").value=prefs.dailyQuestionTarget||30;el("language").value="bn";el("quiz-mode").value=prefs.quizMode||"timed";el("difficulty").value=prefs.difficultyPreference||"adaptive";el("display-name").value=prefs.publicDisplayName||"";
    el("leaderboard-visible").checked=prefs.leaderboardVisible!==false;el("username-visible").checked=!!prefs.usernameVisible;el("reminder").checked=false;el("revision-sound").checked=prefs.revisionSoundEnabled!==false;el("revision-vibration").checked=prefs.revisionVibrationEnabled===true;
    localPreference("revisionSoundEnabled",el("revision-sound").checked);localPreference("revisionVibrationEnabled",el("revision-vibration").checked);checkValues("exam-checks",prefs.targetExams||[]);checkValues("subject-checks",prefs.preferredSubjects||[]);
  }

  function testSound(){
    var message=el("sound-message");message.textContent="শব্দ বাজানো হচ্ছে...";
    try{var AudioCtor=window.AudioContext||window.webkitAudioContext;if(!AudioCtor)throw new Error("unsupported");var context=new AudioCtor(),now=context.currentTime,oscillator=context.createOscillator(),gain=context.createGain();oscillator.type="sine";oscillator.frequency.setValueAtTime(220,now);oscillator.frequency.exponentialRampToValueAtTime(150,now+.16);gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.09,now+.018);gain.gain.exponentialRampToValueAtTime(.0001,now+.17);oscillator.connect(gain);gain.connect(context.destination);oscillator.start(now);oscillator.stop(now+.18);oscillator.onended=function(){context.close();message.textContent="পরীক্ষার শব্দ বাজানো হয়েছে।"}}catch(error){message.textContent="এই ডিভাইসে শব্দ চালু করা যায়নি।"}
  }

  function privacyAction(path){return miniappFetch(api(path),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData})}).then(check)}
  function exportData(){var message=el("privacy-message");message.textContent="ডেটা প্রস্তুত হচ্ছে...";privacyAction("/api/me/data-export").then(function(data){var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="quiz-platform-data-export.json";link.click();URL.revokeObjectURL(link.href);message.textContent="ডেটা এক্সপোর্ট তৈরি হয়েছে।"}).catch(function(){message.textContent="ডেটা এক্সপোর্ট করা যায়নি। Mini App আবার খুলে চেষ্টা করুন।"})}
  function requestDeletion(){var message=el("privacy-message");if(!window.confirm("৭ দিন পরে আপনার অ্যাকাউন্ট ও শেখার ডেটা স্থায়ীভাবে মুছে যাবে। অনুরোধটি রাখবেন?"))return;privacyAction("/api/me/account-deletion").then(function(result){message.textContent="অনুরোধ রাখা হয়েছে। "+result.gracePeriodDays+" দিনের মধ্যে চাইলে বাতিল করুন।"}).catch(function(){message.textContent="মুছে ফেলার অনুরোধ রাখা যায়নি।"})}
  function cancelDeletion(){var message=el("privacy-message");privacyAction("/api/me/account-deletion/cancel").then(function(result){message.textContent=result.cancelled?"মুছে ফেলার অনুরোধ বাতিল হয়েছে।":"কোনো সক্রিয় অনুরোধ পাওয়া যায়নি।"}).catch(function(){message.textContent="অনুরোধ বাতিল করা যায়নি।"})}

  function savePreferences(event){
    event.preventDefault();var message=el("settings-message"),button=el("settings-submit");button.disabled=true;message.textContent="সংরক্ষণ হচ্ছে...";
    var sound=el("revision-sound").checked,vibration=el("revision-vibration").checked;
    miniappFetch(api("/api/me/preferences"),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData,targetExams:checked("exam-checks"),preferredSubjects:checked("subject-checks"),dailyQuestionTarget:+el("daily-target").value,preferredLanguage:el("language").value,difficultyPreference:el("difficulty").value,quizMode:el("quiz-mode").value,leaderboardVisible:el("leaderboard-visible").checked,publicDisplayName:el("display-name").value.trim()||null,usernameVisible:el("username-visible").checked,dailyReminderEnabled:false,revisionSoundEnabled:sound,revisionVibrationEnabled:vibration})})
      .then(check).then(function(){localPreference("revisionSoundEnabled",sound);localPreference("revisionVibrationEnabled",vibration);message.textContent="সেটিং সংরক্ষিত হয়েছে।"}).catch(function(){message.textContent="সেটিং সংরক্ষণ করা যায়নি।"}).finally(function(){button.disabled=false});
  }
})();
