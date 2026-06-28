const BASES=["http://127.0.0.1:8765","http://localhost:8765"];
let BASE=BASES[0];
let progressTimer=null;
let currentUrl="";
let licenseValid=false;

function $(id){return document.getElementById(id)}
function setStatus(msg,type=""){const el=$("status");el.textContent=msg;el.className="status show"+(type?" "+type:"")}
function setProgress(percent,detail=""){const wrap=$("progressWrap"),bar=$("progressBar"),text=$("progressText");const safe=Math.max(0,Math.min(100,Number(percent)||0));wrap.className="progress-wrap show";bar.style.width=safe.toFixed(1)+"%";text.textContent=safe.toFixed(1)+"%"+(detail?"\n"+detail:"")}
async function api(path,options={}){let lastErr=null;for(const base of BASES){try{const res=await fetch(base+path,{cache:"no-store",...options});BASE=base;return res}catch(e){lastErr=e}}throw lastErr||new Error("Failed to fetch")}
async function apiJson(path,options={}){const res=await api(path,options);let data={};try{data=await res.json()}catch(e){};if(!res.ok||data.status==="error")throw new Error(data.message||`HTTP ${res.status}`);return data}
async function getCurrentTab(){const [tab]=await chrome.tabs.query({active:true,currentWindow:true});return tab}
function isYouTubeVideo(url){return url&&(url.includes("youtube.com/watch")||url.includes("youtu.be/"))}
function setBtnAvailable(btn,available,title=""){btn.disabled=!available;btn.classList.toggle("unavailable",!available);btn.title=title}
function setAllDownloadButtons(available,title=""){document.querySelectorAll(".btn[data-mode]").forEach(btn=>setBtnAvailable(btn,available,title))}
function serverFailMessage(e){return "無法連到 server。請確認已執行 install.command。\n"+(e&&e.message?e.message:"")}

function toggleSettings(){
  const panel=$("settingsPanel");
  const area=$("downloadArea");
  const open=panel.classList.toggle("show");
  area.style.display=open?"none":"block";
  $("settingsToggle").textContent=open?"✕ 關閉":"⚙️ 設定";
}

async function pingServer(){
  const data=await apiJson("/ping");
  licenseValid=!!(data.license&&data.license.valid);
  if(data.version) $("versionLine").textContent="版本："+data.version;
  return data;
}

async function checkLicense(){
  try{
    const ping=await pingServer();
    if(!ping.license||ping.license.valid===false){
      setAllDownloadButtons(false,"尚未啟用授權");
      setStatus("✗ 尚未啟用序號，不能下載\n請執行 install.command 完成安裝與授權","err");
      return false;
    }
    return true;
  }catch(e){
    setAllDownloadButtons(false,"無法連到 server");
    setStatus("✗ "+serverFailMessage(e),"err");
    return false;
  }
}

async function pollProgress(jobId){
  if(progressTimer)clearInterval(progressTimer);
  progressTimer=setInterval(async()=>{
    try{
      const data=await apiJson(`/progress?id=${encodeURIComponent(jobId)}`);
      const detail=[data.message||"",data.speed?`速度：${data.speed}`:"",data.eta?`剩餘：${data.eta}`:"",data.file?`檔名：${data.file}`:""].filter(Boolean).join("\n");
      setProgress(data.progress||0,detail);
      if(data.status==="done"){clearInterval(progressTimer);progressTimer=null;setProgress(100,data.file?`完成：${data.file}`:"完成");setStatus("✓ 下載完成","ok")}
      else if(data.status==="error"){clearInterval(progressTimer);progressTimer=null;setStatus("✗ 錯誤："+(data.message||"下載失敗"),"err")}
    }catch(e){clearInterval(progressTimer);progressTimer=null;setStatus("✗ 讀取進度失敗","err")}
  },800);
}

async function download(url,mode){
  setAllDownloadButtons(false,"下載中...");
  setStatus("檢查授權...");
  const ok=await checkLicense();
  if(!ok){setAllDownloadButtons(true);return}
  setStatus("傳送下載指令...");setProgress(0,"準備中...");
  try{
    const data=await apiJson("/download",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,mode})});
    setStatus("✓ 已開始下載到 Downloads","ok");
    pollProgress(data.job_id);
  }catch(e){
    setStatus("✗ 錯誤："+e.message,"err");
  }finally{
    setAllDownloadButtons(true);
  }
}

async function deactivateLicense(){
  if(!confirm("確定解除授權？解除後本機會鎖定下載，序號可重新綁定其他裝置。"))return;
  try{
    await apiJson("/license/deactivate",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    licenseValid=false;
    setAllDownloadButtons(false,"尚未啟用授權");
    setStatus("✓ 已解除授權，下載已鎖定","ok");
  }catch(e){setStatus("✗ 解除授權失敗\n"+serverFailMessage(e),"err")}
}

async function rebindLicense(){
  const key=prompt("輸入要重新綁定到此裝置的序號：");
  if(!key)return;
  try{
    const data=await apiJson("/license/rebind",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({license:key.trim()})});
    if(!data.result||!data.result.valid)throw new Error((data.result&&data.result.message)||"重新綁定失敗");
    licenseValid=true;
    setStatus("✓ 已重新綁定此裝置","ok");
  }catch(e){setStatus("✗ 重新綁定失敗\n"+serverFailMessage(e),"err")}
}

async function manualUpdate(){
  setStatus("檢查更新中...");
  try{
    const check=await apiJson("/update/check");
    if(check.has_update===false){setStatus(`✓ 目前已是最新版\n版本：${check.current_version}`,"ok");return}
    if(!confirm(`發現新版 ${check.latest_version}\n目前版本 ${check.current_version}\n\n${check.message||""}\n\n要立即更新嗎？`))return;
    const data=await apiJson("/update/install",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    setStatus("✓ "+data.message,"ok");
  }catch(e){
    const msg=e.message||"";
    if(msg.includes("update_json_url")) setStatus("更新伺服器尚未設定，請聯絡賣家取得更新。","");
    else setStatus("✗ 更新失敗\n"+msg,"err");
  }
}

document.addEventListener("DOMContentLoaded",async()=>{
  $("settingsToggle").addEventListener("click",toggleSettings);
  $("updateBtn").addEventListener("click",manualUpdate);
  $("deactivateBtn").addEventListener("click",deactivateLicense);
  $("rebindBtn").addEventListener("click",rebindLicense);

  try{
    const tab=await getCurrentTab();
    if(!tab||!isYouTubeVideo(tab.url)){$("notYoutube").style.display="block";return}
    currentUrl=tab.url;
    $("main").style.display="block";
    $("pageUrl").textContent=tab.url;
    // 所有按鈕預設可用，按下去才偵測
    setAllDownloadButtons(true);
    document.querySelectorAll(".btn[data-mode]").forEach(btn=>btn.addEventListener("click",()=>{
      if(!btn.disabled)download(tab.url,btn.dataset.mode);
    }));
    // 只做授權檢查，不偵測解析度
    try{
      const ping=await pingServer();
      if(!ping.license||ping.license.valid===false){
        setAllDownloadButtons(false,"尚未啟用授權");
        setStatus("✗ 尚未啟用序號，不能下載","err");
      }
    }catch(e){
      setAllDownloadButtons(false,"無法連到 server");
      setStatus("✗ "+serverFailMessage(e),"err");
    }
  }catch(e){
    $("main").style.display="block";
    setStatus("✗ 無法讀取目前網址\n"+e.message,"err");
  }
});
