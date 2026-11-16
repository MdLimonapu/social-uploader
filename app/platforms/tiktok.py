"""TikTok Content Posting API: OAuth v2 + direct post via FILE_UPLOAD."""
import time, secrets, urllib.parse, requests
from pathlib import Path
from ..config import BASE_URL, env, load_token, save_token, log

AUTH = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"
INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
CREATOR = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
PREFERENCE = ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]
REDIRECT = f"{BASE_URL}/oauth/tiktok/callback"
CHUNK = 10 * 1024 * 1024
_state = {}

def configured(): return bool(env("TIKTOK_CLIENT_KEY") and env("TIKTOK_CLIENT_SECRET"))
def connected(): return bool(load_token("tiktok"))

def auth_url():
    s = secrets.token_urlsafe(16); _state["s"] = s
    q = {"client_key": env("TIKTOK_CLIENT_KEY"), "scope": "user.info.basic,video.publish",
         "response_type": "code", "redirect_uri": REDIRECT, "state": s}
    return AUTH + "?" + urllib.parse.urlencode(q)

def _save(r):
    r.raise_for_status(); d = r.json()
    if "access_token" not in d: raise RuntimeError(f"TikTok token error: {d}")
    d["expires_at"] = time.time() + d.get("expires_in", 0) - 60
    save_token("tiktok", d); return d

def callback(code, state):
    if state != _state.get("s"): raise RuntimeError("bad OAuth state")
    return _save(requests.post(TOKEN, data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT}, timeout=30))

def access_token():
    t = load_token("tiktok")
    if not t: raise RuntimeError("TikTok not connected")
    if time.time() > t.get("expires_at", 0):
        t = _save(requests.post(TOKEN, data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token", "refresh_token": t["refresh_token"]}, timeout=30))
    return t["access_token"]

def chunk_plan(size):
    """TikTok rules: chunks 5-64MB, last chunk may be up to 128MB; files <=64MB in one chunk."""
    if size <= 64 * 1024 * 1024: return size, 1
    return CHUNK, size // CHUNK

def pick_privacy(options, wanted=None):
    """Return (privacy_level, warning|None). Prefer wanted (default PUBLIC_TO_EVERYONE), else most public allowed."""
    wanted = wanted or env("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE") or "PUBLIC_TO_EVERYONE"
    if not options: return wanted, None
    if wanted in options: return wanted, None
    best = next((p for p in PREFERENCE if p in options), options[0])
    msg = (f"TikTok didn't allow {wanted} for this account/app (allowed: {', '.join(options)}); posted as {best}.")
    if best == "SELF_ONLY": msg += " Unaudited TikTok apps can only post privately – submit your app for TikTok's Content Posting API audit to post publicly."
    return best, msg

def creator_info(headers):
    r = requests.post(CREATOR, headers=headers, timeout=30).json()
    return r.get("data") or {}

def build_init(size, caption, privacy=None):
    cs, n = chunk_plan(size)
    return {"post_info": {"title": caption[:2200], "privacy_level": privacy or env("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE") or "PUBLIC_TO_EVERYONE",
                          "disable_comment": False, "disable_duet": False, "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": cs, "total_chunk_count": n}}

def upload(path: Path, title: str, caption: str):
    tok = access_token(); size = path.stat().st_size
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}
    try: opts = creator_info(h).get("privacy_level_options") or []
    except Exception as e: opts = []; log.warning("TikTok creator_info failed: %s", e)
    privacy, warn = pick_privacy(opts)
    if warn: log.warning("TikTok: %s", warn)
    body = build_init(size, caption or title, privacy)
    r = requests.post(INIT, json=body, headers=h, timeout=60).json()
    if r.get("error", {}).get("code") not in (None, "ok"): raise RuntimeError(f"TikTok init: {r['error']}")
    pid, up = r["data"]["publish_id"], r["data"]["upload_url"]
    cs, n = body["source_info"]["chunk_size"], body["source_info"]["total_chunk_count"]
    with open(path, "rb") as f:
        for i in range(n):
            start = i * cs; end = size - 1 if i == n - 1 else start + cs - 1
            f.seek(start); data = f.read(end - start + 1)
            rr = requests.put(up, data=data, timeout=600, headers={"Content-Type": "video/mp4",
                 "Content-Length": str(len(data)), "Content-Range": f"bytes {start}-{end}/{size}"})
            if rr.status_code not in (200, 201, 206): raise RuntimeError(f"TikTok chunk {i}: {rr.status_code} {rr.text}")
    for _ in range(60):
        s = requests.post(STATUS, json={"publish_id": pid}, headers=h, timeout=30).json().get("data", {})
        log.info("TikTok status %s", s.get("status"))
        if s.get("status") == "PUBLISH_COMPLETE": return {"publish_id": pid, "status": "PUBLISH_COMPLETE", "visibility": privacy, **({"warning": warn} if warn else {})}
        if s.get("status") == "FAILED": raise RuntimeError(f"TikTok failed: {s.get('fail_reason')}")
        time.sleep(5)
    return {"publish_id": pid, "status": "processing (check TikTok app)", "visibility": privacy, **({"warning": warn} if warn else {})}
