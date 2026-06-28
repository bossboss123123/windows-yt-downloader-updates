#!/usr/bin/env python3
# 簡易授權 API 範例。正式販售時可部署在 VPS / Render / Railway / Cloud Run。
# 端點：/activate /verify /deactivate /rebind
import json, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8788
DB_PATH = Path(__file__).resolve().parent / "licenses_db.json"
DEFAULT_DB = {
  "DEMO-1234": {
    "status": "active",
    "max_devices": 1,
    "devices": {},
    "owner": "DEMO USER"
  }
}

def load_db():
    if not DB_PATH.exists():
        save_db(DEFAULT_DB)
        return json.loads(json.dumps(DEFAULT_DB))
    return json.loads(DB_PATH.read_text(encoding="utf-8"))

def save_db(db):
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

def mask(key):
    return key[:4] + "***" + key[-4:] if len(key) > 4 else key

def ok(key, device_id, message):
    return {"valid": True, "message": message, "license_masked": mask(key), "device_id": device_id}

def fail(device_id, message):
    return {"valid": False, "message": message, "device_id": device_id}

def activate_or_verify(data, allow_new=True):
    key = (data.get("license") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    if not key or not device_id:
        return fail(device_id, "缺少序號或 Device ID")
    db = load_db()
    lic = db.get(key)
    if not lic or lic.get("status") != "active":
        return fail(device_id, "序號不存在或已停用")
    devices = lic.setdefault("devices", {})
    if device_id in devices:
        devices[device_id]["last_seen"] = int(time.time())
        save_db(db)
        return ok(key, device_id, "授權有效")
    if not allow_new:
        return fail(device_id, "此裝置尚未啟用")
    if len(devices) >= int(lic.get("max_devices", 1)):
        return fail(device_id, "此序號已綁定其他裝置，請先解除授權或使用重新綁定")
    devices[device_id] = {"activated_at": int(time.time()), "last_seen": int(time.time())}
    save_db(db)
    return ok(key, device_id, "啟用成功")

def deactivate(data):
    key = (data.get("license") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    db = load_db()
    lic = db.get(key)
    if lic and device_id in lic.get("devices", {}):
        del lic["devices"][device_id]
        save_db(db)
    return {"valid": False, "ok": True, "message": "已解除此裝置授權", "device_id": device_id}

def rebind(data):
    key = (data.get("license") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    db = load_db()
    lic = db.get(key)
    if not lic or lic.get("status") != "active":
        return fail(device_id, "序號不存在或已停用")
    lic["devices"] = {device_id: {"activated_at": int(time.time()), "last_seen": int(time.time())}}
    save_db(db)
    return ok(key, device_id, "已重新綁定到此裝置")

class H(BaseHTTPRequestHandler):
    def headers(self, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()
    def out(self, obj, code=200):
        self.headers(code)
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    def do_OPTIONS(self): self.headers(200)
    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8") or "{}")
            if self.path == "/activate": self.out(activate_or_verify(data, True)); return
            if self.path == "/verify": self.out(activate_or_verify(data, False)); return
            if self.path == "/deactivate": self.out(deactivate(data)); return
            if self.path == "/rebind": self.out(rebind(data)); return
            self.out({"valid": False, "message": "not found"}, 404)
        except Exception as e:
            self.out({"valid": False, "message": str(e)}, 500)
    def log_message(self, fmt, *args): print(fmt % args)

if __name__ == "__main__":
    load_db()
    print(f"License API running: http://127.0.0.1:{PORT}")
    print("測試序號：DEMO-1234")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
