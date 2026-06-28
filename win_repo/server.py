#!/usr/bin/env python3
import json, os, re, shutil, subprocess, threading, time, uuid, hashlib, platform, urllib.request, zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8765
BASE_DIR = Path(__file__).resolve().parent
BUNDLED_BIN = BASE_DIR / "bin"
CONFIG_PATH = BASE_DIR / "config.json"
LICENSE_PATH = BASE_DIR / "license.key"
DEVICE_PATH = BASE_DIR / "device_id.json"
UPDATE_TMP = BASE_DIR / "_update.zip"
BACKUP_DIR = BASE_DIR / "_backup"
JOBS = {}
LOCK = threading.Lock()

APP_VERSION = "4.0.7"
DEFAULT_CONFIG = {"require_license":True,"license_api_url":"","update_json_url":"","download_dir":"~/Downloads"}

if platform.system() == "Windows":
    os.environ["PATH"] = ";".join([str(BUNDLED_BIN), os.environ.get("PATH", "")])
else:
    os.environ["PATH"] = ":".join([str(BUNDLED_BIN),"/opt/homebrew/bin","/usr/local/bin","/usr/bin","/bin","/usr/sbin","/sbin",os.environ.get("PATH","")])
PERCENT_RE = re.compile(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?)%")
SPEED_RE = re.compile(r"\bat\s+([0-9.]+[KMG]i?B/s)")
ETA_RE = re.compile(r"\bETA\s+([0-9:]+)")
DEST_RE = re.compile(r"\[download\] Destination:\s+(.+)$")
MERGE_RE = re.compile(r"\[Merger\] Merging formats into\s+\"(.+)\"")
EXTRACT_RE = re.compile(r"\[ExtractAudio\] Destination:\s+(.+)$")
RESOLUTION_LIST = [("video-4k",2160,"4K (2160p)"),("video-2k",1440,"2K (1440p)"),("video-1080",1080,"1080p"),("video-720",720,"720p"),("video-480",480,"480p"),("video-360",360,"360p"),("video-240",240,"240p"),("video-144",144,"144p")]

def load_config():
    if not CONFIG_PATH.exists(): save_config(DEFAULT_CONFIG); return dict(DEFAULT_CONFIG)
    try:
        data=json.loads(CONFIG_PATH.read_text(encoding="utf-8")); out=dict(DEFAULT_CONFIG); out.update(data); return out
    except Exception: return dict(DEFAULT_CONFIG)

def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
def app_version(): return APP_VERSION
def download_dir(): return os.path.expanduser(load_config().get("download_dir","~/Downloads"))

def version_tuple(v):
    nums=[]
    for p in str(v).split("."):
        try: nums.append(int(p))
        except Exception: nums.append(0)
    while len(nums)<3: nums.append(0)
    return tuple(nums[:3])

def device_id():
    if DEVICE_PATH.exists():
        try:
            d=json.loads(DEVICE_PATH.read_text(encoding="utf-8"));
            if d.get("device_id"): return d["device_id"]
        except Exception: pass
    raw=f"{platform.node()}|{platform.system()}|{platform.machine()}|{os.path.expanduser('~')}"
    did=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    DEVICE_PATH.write_text(json.dumps({"device_id":did},ensure_ascii=False,indent=2),encoding="utf-8")
    return did

def mask_license(key):
    key=(key or "").strip()
    if len(key)<=4: return key
    return key[:4] + "***" + key[-4:]

def read_license_key(): return LICENSE_PATH.read_text(encoding="utf-8").strip() if LICENSE_PATH.exists() else ""
def save_license_key(key): LICENSE_PATH.write_text(key.strip(),encoding="utf-8")
def clear_license_local():
    LICENSE_PATH.unlink(missing_ok=True)
    # 保留 device_id，避免同機重綁時裝置識別改變。

def api_base(): return load_config().get("license_api_url","").strip().rstrip("/")
def api_post(path, payload):
    base=api_base()
    if not base: raise RuntimeError("尚未設定 license_api_url")
    url = base if base.endswith(path) else base + path
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json","User-Agent":"YTDownloader"})
    with urllib.request.urlopen(req,timeout=12) as r: return json.loads(r.read().decode("utf-8"))

# ── 本機授權資料庫 ──────────────────────────────────────────
ACTIVATED_PATH = BASE_DIR / "activated_licenses.json"
ACTIVATED_LOCK = threading.Lock()

def load_activated():
    with ACTIVATED_LOCK:
        if not ACTIVATED_PATH.exists(): return {}
        try: return json.loads(ACTIVATED_PATH.read_text(encoding="utf-8"))
        except Exception: return {}

def save_activated(db):
    with ACTIVATED_LOCK:
        ACTIVATED_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

def valid_keys_set():
    cfg = load_config()
    keys = cfg.get("valid_licenses", [])
    return {k.strip().upper() for k in keys if k.strip()}

def local_verify(key):
    key = key.strip().upper()
    if key not in valid_keys_set():
        return {"valid": False, "message": "序號無效", "device_id": device_id()}
    db = load_activated()
    entry = db.get(key)
    did = device_id()
    if entry and entry.get("device_id") and entry["device_id"] != did:
        return {"valid": False, "message": "此序號已綁定其他裝置，請先解除授權或使用重新綁定", "device_id": did}
    return {"valid": True, "message": "授權有效", "device_id": did, "license_masked": mask_license(key)}

def local_activate(key):
    key = key.strip().upper()
    if key not in valid_keys_set():
        return {"valid": False, "message": "序號無效", "device_id": device_id()}
    db = load_activated(); did = device_id(); entry = db.get(key)
    if entry and entry.get("device_id") and entry["device_id"] != did:
        return {"valid": False, "message": "此序號已綁定其他裝置", "device_id": did}
    db[key] = {"device_id": did, "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_activated(db)
    return {"valid": True, "message": "啟用成功", "device_id": did, "license_masked": mask_license(key)}

def local_deactivate(key):
    key = key.strip().upper(); db = load_activated()
    if key in db: del db[key]; save_activated(db)
    return {"ok": True, "message": "已解除授權"}

def local_rebind(key):
    key = key.strip().upper()
    if key not in valid_keys_set():
        return {"valid": False, "message": "序號無效", "device_id": device_id()}
    db = load_activated(); did = device_id()
    entry = db.get(key)
    # 重新綁定只允許已曾啟用過的序號（entry 存在），否則請用啟用
    if not entry:
        return {"valid": False, "message": "此序號尚未啟用過，請使用啟用序號", "device_id": did}
    if entry.get("device_id") == did:
        return {"valid": False, "message": "此序號已綁定本裝置，無需重新綁定", "device_id": did}
    db[key] = {"device_id": did, "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_activated(db)
    return {"valid": True, "message": "重新綁定成功", "device_id": did, "license_masked": mask_license(key)}

# ── 公開授權函數 ─────────────────────────────────────────────
def verify_license(key=None):
    cfg=load_config(); key=(key if key is not None else read_license_key()).strip()
    if not cfg.get("require_license",True): return {"valid":True,"message":"授權未強制啟用","device_id":device_id(),"license_masked":mask_license(key)}
    if not key: return {"valid":False,"message":"尚未輸入序號","device_id":device_id()}
    if api_base():
        try:
            res=api_post("/verify", {"license":key,"device_id":device_id(),"version":app_version()})
            res.setdefault("device_id", device_id()); res.setdefault("license_masked", mask_license(key)); return res
        except Exception as e: return {"valid":False,"message":f"授權伺服器連線失敗：{e}","device_id":device_id()}
    return local_verify(key)

def activate_license(key):
    key=key.strip()
    if api_base():
        result=api_post("/activate", {"license":key,"device_id":device_id(),"version":app_version()})
        result.setdefault("device_id",device_id()); result.setdefault("license_masked",mask_license(key))
    else:
        result=local_activate(key)
    if result.get("valid"): save_license_key(key)
    return result

def deactivate_license():
    key=read_license_key()
    if key and api_base():
        try: remote=api_post("/deactivate", {"license":key,"device_id":device_id(),"version":app_version()})
        except Exception as e: remote={"ok":False,"message":f"遠端解除失敗，但已解除本機授權：{e}"}
    else:
        remote=local_deactivate(key) if key else {"ok":True,"message":"本機已解除授權"}
    clear_license_local()
    return {"valid":False,"message":remote.get("message","已解除授權"),"device_id":device_id(),"remote":remote}

def rebind_license(key):
    key=key.strip()
    if api_base():
        result=api_post("/rebind", {"license":key,"device_id":device_id(),"version":app_version()})
        result.setdefault("device_id",device_id()); result.setdefault("license_masked",mask_license(key))
    else:
        result=local_rebind(key)
    if result.get("valid"): save_license_key(key)
    return result

def require_valid_license():
    lic=verify_license()
    if not lic.get("valid"): raise PermissionError("尚未啟用序號，不能下載：" + lic.get("message", ""))
    return lic

def tool_path(name):
    path=shutil.which(name)
    if not path: raise FileNotFoundError(f"找不到 {name}，請確認已安裝 yt-dlp 與 ffmpeg")
    return path

def video_format(height): return f"bv*[height={height}][ext=mp4]+ba[ext=m4a]/bv*[height={height}]+ba/b[height={height}][ext=mp4]/b[height={height}]"
def ytdlp_format(mode):
    fm={"video-4k":video_format(2160),"video-2k":video_format(1440),"video-1080":video_format(1080),"video-720":video_format(720),"video-480":video_format(480),"video-360":video_format(360),"video-240":video_format(240),"video-144":video_format(144),"best":"bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"}
    return fm.get(mode,fm["best"])

def build_cmd(url,mode):
    ytdlp=tool_path("yt-dlp"); outtmpl=os.path.join(download_dir(),"%(title).100B-%(id)s-"+mode+".%(ext)s")
    base=[ytdlp,"--no-playlist","--newline","--no-color","--restrict-filenames","-o",outtmpl]
    if mode=="audio-mp3": return base+["-x","--audio-format","mp3","--audio-quality","0",url]
    if mode=="audio-m4a": return base+["-x","--audio-format","m4a","--audio-quality","0",url]
    return base+["-f",ytdlp_format(mode),"--merge-output-format","mp4","--remux-video","mp4",url]

def list_formats(url):
    lic=require_valid_license(); ytdlp=tool_path("yt-dlp")
    proc=subprocess.run([ytdlp,"-J","--no-playlist",url],capture_output=True,text=True)
    if proc.returncode!=0: raise RuntimeError((proc.stderr or proc.stdout or "無法解析影片格式")[-800:])
    info=json.loads(proc.stdout); heights=set()
    for f in info.get("formats",[]):
        h=f.get("height"); v=f.get("vcodec")
        if isinstance(h,int) and h>0 and v and v!="none": heights.add(h)
    formats=[{"mode":"best","label":"最佳畫質","available":True}]
    for mode,height,label in RESOLUTION_LIST: formats.append({"mode":mode,"height":height,"label":label,"available":height in heights,"exact":height in heights})
    formats += [{"mode":"audio-mp3","label":"MP3","available":True},{"mode":"audio-m4a","label":"M4A","available":True}]
    return {"status":"ok","title":info.get("title",""),"max_height":max(heights) if heights else None,"heights":sorted(heights,reverse=True),"formats":formats,"license":lic}

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def read_url_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"YTDownloader"})
    with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read().decode("utf-8"))
def check_update():
    cfg=load_config(); current=APP_VERSION; url=cfg.get("update_json_url","").strip()
    if not url: return {"status":"error","message":"尚未設定 update_json_url","current_version":current,"has_update":False}
    data=read_url_json(url); latest=data.get("version","0.0.0"); has=version_tuple(latest)>version_tuple(current)
    return {"status":"ok","current_version":current,"latest_version":latest,"has_update":has,"message":data.get("message",""),"download_url":data.get("download_url",""),"sha256":data.get("sha256","")}
def apply_update():
    info=check_update()
    if info.get("status")!="ok" or not info.get("has_update"): return {"status":"ok","updated":False,"message":info.get("message","目前已是最新版"),**info}
    url=info.get("download_url","")
    if not url: return {"status":"error","message":"update.json 沒有 download_url"}
    with urllib.request.urlopen(url,timeout=60) as r: UPDATE_TMP.write_bytes(r.read())
    # SHA256 驗證已停用
    BACKUP_DIR.mkdir(exist_ok=True); backup=BACKUP_DIR/time.strftime("%Y%m%d-%H%M%S"); backup.mkdir(exist_ok=True)
    update_files={"server.py","popup.html","popup.js","manifest.json","README.txt"}
    for name in update_files:
        src=BASE_DIR/name
        if src.exists(): shutil.copy2(src,backup/name)
    old_license=read_license_key()
    # 移除 macOS quarantine/保護，讓檔案可以被覆蓋
    import subprocess
    if platform.system() != "Windows":
        subprocess.run(["xattr","-rd","com.apple.quarantine",str(BASE_DIR)],capture_output=True)
        subprocess.run(["chmod","-R","u+w",str(BASE_DIR)],capture_output=True)
    with zipfile.ZipFile(UPDATE_TMP,"r") as z:
        for member in z.namelist():
            name=Path(member).name
            if name in update_files:
                z.extract(member,BASE_DIR); extracted=BASE_DIR/member; final=BASE_DIR/name
                if extracted!=final and extracted.exists(): shutil.move(str(extracted),str(final))
    if old_license: save_license_key(old_license)
    UPDATE_TMP.unlink(missing_ok=True)
    # 自動重啟 server（3秒後）
    import subprocess, threading
    def restart():
        import time; time.sleep(3)
        if platform.system() == "Windows":
            subprocess.run(["schtasks","/run","/tn","YTDownloaderServer"], capture_output=True)
        else:
            subprocess.run(["launchctl","kickstart","-k",f"gui/{os.getuid()}/com.ytdownloader.server"], capture_output=True)
    threading.Thread(target=restart,daemon=True).start()
    return {"status":"ok","updated":True,"message":"更新完成，背景服務將自動重啟。請重新整理 Chrome 外掛。",**info}

def set_job(job_id,**kwargs):
    with LOCK: JOBS.setdefault(job_id,{}).update(kwargs)
def get_job(job_id):
    with LOCK: return dict(JOBS.get(job_id,{}))
def run_job(job_id,url,mode):
    try:
        require_valid_license(); cmd=build_cmd(url,mode); os.makedirs(download_dir(),exist_ok=True)
        set_job(job_id,status="downloading",progress=0,message="準備下載...",file="",speed="",eta="")
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        last_file=""; last_line=""
        for line in proc.stdout:
            line=line.strip()
            if not line: continue
            last_line=line; m=PERCENT_RE.search(line)
            if m:
                percent=float(m.group(1)); sp=SPEED_RE.search(line); eta=ETA_RE.search(line)
                set_job(job_id,progress=percent,message=f"下載中 {percent:.1f}%",speed=sp.group(1) if sp else "",eta=eta.group(1) if eta else "")
            for rx in (DEST_RE,MERGE_RE,EXTRACT_RE):
                fm=rx.search(line)
                if fm: last_file=os.path.basename(fm.group(1).strip()); set_job(job_id,file=last_file)
            if "[Merger]" in line: set_job(job_id,progress=99,message="合併影片與音訊...")
            elif "[VideoRemuxer]" in line or "[VideoConvertor]" in line: set_job(job_id,progress=99,message="轉成 MP4...")
            elif "Deleting original file" in line: set_job(job_id,message="清理暫存檔...")
        code=proc.wait(); set_job(job_id,status="done" if code==0 else "error",progress=100 if code==0 else get_job(job_id).get("progress",0),message="完成" if code==0 else (last_line or "下載失敗"),file=last_file or ("完成" if code==0 else ""))
    except Exception as e: set_job(job_id,status="error",message=str(e))

class Handler(BaseHTTPRequestHandler):
    def _headers(self,code=200):
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Private-Network","true"); self.end_headers()
    def write_json(self,obj,code=200): self._headers(code); self.wfile.write(json.dumps(obj,ensure_ascii=False).encode("utf-8"))
    def do_OPTIONS(self): self._headers(200)
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=="/ping" or parsed.path=="/license/status": self.write_json({"status":"ok","version":app_version(),"device_id":device_id(),"license":verify_license()}); return
        if parsed.path=="/formats":
            try:
                url=parse_qs(parsed.query).get("url",[""])[0]
                if not url: raise ValueError("沒有 URL")
                self.write_json(list_formats(url))
            except PermissionError as e: self.write_json({"status":"error","message":str(e)},403)
            except Exception as e: self.write_json({"status":"error","message":str(e)},500)
            return
        if parsed.path=="/progress":
            job_id=parse_qs(parsed.query).get("id",[""])[0]; job=get_job(job_id)
            self.write_json(job if job else {"status":"error","message":"找不到下載工作"}, 200 if job else 404); return
        if parsed.path in ("/check_update","/update/check"):
            try: self.write_json(check_update())
            except Exception as e: self.write_json({"status":"error","message":str(e)},500)
            return
        self.write_json({"status":"error","message":"not found"},404)
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length","0")); body=self.rfile.read(length).decode("utf-8") if length else "{}"; data=json.loads(body)
            if self.path in ("/activate","/license/activate"):
                key=data.get("license","").strip()
                if not key: raise ValueError("沒有輸入序號")
                result=activate_license(key); self.write_json({"status":"ok","result":result,"version":app_version(),"device_id":device_id()}); return
            if self.path=="/license/deactivate": self.write_json({"status":"ok","result":deactivate_license(),"version":app_version(),"device_id":device_id()}); return
            if self.path=="/license/rebind":
                key=data.get("license","").strip()
                if not key: raise ValueError("沒有輸入序號")
                result=rebind_license(key); self.write_json({"status":"ok","result":result,"version":app_version(),"device_id":device_id()}); return
            if self.path in ("/update","/update/install"): self.write_json(apply_update()); return
            if self.path=="/download":
                try: require_valid_license()
                except PermissionError as e: self.write_json({"status":"error","message":str(e)},403); return
                url=data.get("url",""); mode=data.get("mode","best")
                if not url: raise ValueError("沒有 URL")
                job_id=uuid.uuid4().hex
                with LOCK: JOBS[job_id]={"status":"queued","progress":0,"message":"排隊中...","file":"","speed":"","eta":"","created":time.time()}
                threading.Thread(target=run_job,args=(job_id,url,mode),daemon=True).start(); self.write_json({"status":"ok","job_id":job_id}); return
            self.write_json({"status":"error","message":"not found"},404)
        except Exception as e: self.write_json({"status":"error","message":str(e)},500)
    def log_message(self,fmt,*args): print(fmt % args)
class ReuseServer(ThreadingHTTPServer): allow_reuse_address=True
if __name__=="__main__":
    load_config()
    print(f"YT Downloader server running: http://127.0.0.1:{PORT}")
    print("版本：",app_version()); print("下載位置：",download_dir()); print("裝置 ID：",device_id()); print("授權狀態：",verify_license().get("message","")); print("解析度：最佳、4K、2K、1080p、720p、480p、360p、240p、144p")
    ReuseServer(("127.0.0.1",PORT),Handler).serve_forever()
