"""Jobs (persistent history), scheduler and watch folder."""
import json, secrets, shutil, threading, time, uuid
from datetime import datetime
from pathlib import Path
from .config import ROOT, env, log, VIDEO_EXT
from .platforms import youtube, tiktok, meta, instagram

PLATFORMS = ["youtube", "tiktok", "instagram", "facebook"]
DB = ROOT / "data" / "jobs.json"
JOBS: dict = {}
PUBLIC_FILES: dict = {}
_lock = threading.RLock()

# ---------- persistence ----------
def save_jobs():
    with _lock:
        DB.parent.mkdir(exist_ok=True)
        tmp = DB.with_suffix(".tmp"); tmp.write_text(json.dumps(JOBS, indent=1)); tmp.replace(DB)

def load_jobs():
    with _lock:
        JOBS.clear()
        if DB.exists():
            try: JOBS.update(json.loads(DB.read_text()))
            except Exception: log.exception("could not read %s", DB)
        for j in JOBS.values():   # app was stopped mid-upload
            if j["state"] == "running":
                j["state"] = "finished"
                for r in j["results"].values():
                    if r["state"] in ("running", "queued"): r.update(state="error", error="interrupted (app restarted)")
        save_jobs()

def status():
    return {
        "youtube": {"configured": youtube.configured(), "connected": youtube.connected()},
        "tiktok": {"configured": tiktok.configured(), "connected": tiktok.connected()},
        "facebook": {"configured": meta.configured(), "connected": meta.fb_connected()},
        "instagram": {"configured": instagram.configured() or meta.configured(), "connected": instagram.connected() or meta.ig_connected(),
                      "public_url": bool(env("PUBLIC_BASE_URL")), "via": "instagram_login" if instagram.connected() else ("facebook_page" if meta.ig_connected() else "")},
    }

def _public_url(path: Path, override=""):
    if override: return override
    base = env("PUBLIC_BASE_URL").rstrip("/")
    if not base: return ""
    tok = secrets.token_urlsafe(24); PUBLIC_FILES[tok] = path
    return f"{base}/media/{tok}/{path.name}"

def upload_one(p, path, title, caption, public_url, yt_privacy=None):
    if p == "youtube": return youtube.upload(path, title, caption, yt_privacy)
    if p == "tiktok": return tiktok.upload(path, title, caption)
    if p == "facebook": return meta.upload_facebook(path, title, caption)
    if p == "instagram":   # default: Instagram Login (no FB Page); fallback: FB-Page-linked IG account
        if instagram.connected() or not meta.ig_connected(): return instagram.upload(path, title, caption, _public_url(path, public_url))
        return meta.upload_instagram(path, title, caption, _public_url(path, public_url))
    raise RuntimeError("unknown platform")

def _move_after(j):
    """Watch-folder jobs: move files to done/ or failed/."""
    if not j.get("move_after"): return
    ok = any(r["state"] == "done" for r in j["results"].values())
    dest = ROOT / ("done" if ok else "failed")
    for f in [j["path"]] + ([j["caption_file"]] if j.get("caption_file") else []):
        f = Path(f)
        if f.exists(): shutil.move(str(f), dest / f.name)
    log.info("Moved %s to %s/", j["file"], dest.name)

def _cleanup(j):
    """DELETE_AFTER_POST=true (default): remove the uploaded copy in uploads/ once the job is done."""
    if env("DELETE_AFTER_POST", "true").lower() not in ("1", "true", "yes"): return
    p = Path(j["path"])
    try:
        if p.exists() and p.resolve().parent == (ROOT / "uploads").resolve():
            p.unlink(); j["deleted"] = True; save_jobs(); log.info("Deleted %s after posting", p.name)
    except OSError as e: log.warning("Could not delete %s: %s", p, e)

def run_job(jid):
    j = JOBS[jid]; path = Path(j["path"])
    with _lock: j["state"] = "running"; j["started"] = time.strftime("%Y-%m-%d %H:%M:%S"); save_jobs()
    for p in j["platforms"]:
        j["results"][p] = {"state": "running"}; save_jobs()
        try:
            r = upload_one(p, path, j["title"], j["caption"], j.get("public_url", ""), j.get("yt_privacy"))
            j["results"][p] = {"state": "done", **r}; log.info("[%s] %s OK %s", jid, p, r)
        except Exception as e:
            j["results"][p] = {"state": "error", "error": str(e)}; log.exception("[%s] %s failed", jid, p)
        save_jobs()
    for k in [k for k, v in PUBLIC_FILES.items() if v == path]: PUBLIC_FILES.pop(k)
    with _lock: j["state"] = "finished"; save_jobs()
    _move_after(j)
    _cleanup(j)

def create_job(path: Path, title, caption, platforms, public_url="", source="web", run_at: float | None = None,
               move_after=False, caption_file=None, start=True, yt_privacy=None):
    jid = uuid.uuid4().hex[:8]
    with _lock:
        JOBS[jid] = {"id": jid, "file": path.name, "path": str(path), "title": title, "caption": caption,
                     "platforms": platforms, "public_url": public_url, "source": source, "yt_privacy": yt_privacy,
                     "state": "scheduled" if run_at else "queued", "run_at": run_at,
                     "created": time.strftime("%Y-%m-%d %H:%M:%S"), "move_after": move_after,
                     "caption_file": str(caption_file) if caption_file else None,
                     "results": {p: {"state": "queued"} for p in platforms}}
        save_jobs()
    if not run_at and start: threading.Thread(target=run_job, args=(jid,), daemon=True).start()
    return jid

# ---------- scheduler ----------
def parse_local(s: str) -> float:
    """'2026-10-25T18:30' or '2026-10-25 18:30' in the computer's local time -> epoch seconds."""
    return datetime.fromisoformat(s.strip().replace(" ", "T")).timestamp()

def fmt_local(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""

def cancel(jid):
    with _lock:
        j = JOBS.get(jid)
        if not j or j["state"] != "scheduled": return False
        j["state"] = "cancelled"; save_jobs(); return True

def reschedule(jid, run_at: float):
    with _lock:
        j = JOBS.get(jid)
        if not j or j["state"] not in ("scheduled", "cancelled"): return False
        j["state"], j["run_at"] = "scheduled", run_at; save_jobs(); return True

def due_jobs(now=None):
    now = now or time.time()
    return [j["id"] for j in JOBS.values() if j["state"] == "scheduled" and j["run_at"] and j["run_at"] <= now]

def scheduler_tick(now=None, threaded=True):
    fired = []
    for jid in due_jobs(now):
        with _lock: JOBS[jid]["state"] = "queued"; save_jobs()
        log.info("Scheduler: posting job %s (%s)", jid, JOBS[jid]["file"])
        if threaded: threading.Thread(target=run_job, args=(jid,), daemon=True).start()
        else: run_job(jid)
        fired.append(jid)
    return fired

def scheduler_loop(stop: threading.Event):
    while not stop.is_set():
        try: scheduler_tick()
        except Exception: log.exception("scheduler")
        stop.wait(20)

# ---------- watch folder ----------
def _caption_for(video: Path):
    """.txt: line 1 = title, rest = caption. Optional line 'schedule: YYYY-MM-DD HH:MM'."""
    txt = video.with_suffix(".txt"); run_at = None
    if not txt.exists(): return video.stem, "", None, None
    lines = []
    for ln in txt.read_text(encoding="utf-8").strip().splitlines():
        if ln.lower().startswith("schedule:"):
            try: run_at = parse_local(ln.split(":", 1)[1])
            except ValueError: log.warning("bad schedule line in %s: %s", txt.name, ln)
        else: lines.append(ln)
    title = lines[0] if lines else video.stem
    return title, ("\n".join(lines[1:]).strip() or title), txt, run_at

def watch_loop(stop: threading.Event):
    inbox, seen, busy = ROOT / "inbox", {}, set()
    while not stop.is_set():
        plats = [p.strip() for p in env("WATCH_PLATFORMS", ",".join(PLATFORMS)).split(",") if p.strip() in PLATFORMS]
        for v in sorted(inbox.iterdir()):
            if v.suffix.lower() not in VIDEO_EXT or v in busy: continue
            size = v.stat().st_size
            if seen.get(v) != size: seen[v] = size; continue
            title, cap, txt, run_at = _caption_for(v); busy.add(v)
            if run_at and run_at > time.time():   # park the file in uploads/ until it's due
                nv = ROOT / "uploads" / f"{int(time.time())}_{v.name}"; shutil.move(str(v), nv)
                if txt: shutil.move(str(txt), ROOT / "done" / txt.name)
                create_job(nv, title, cap, plats, source="watch", run_at=run_at)
                log.info("Watch: scheduled %s for %s", v.name, fmt_local(run_at))
            else:
                log.info("Watch: posting %s to %s", v.name, plats)
                create_job(v, title, cap, plats, source="watch", move_after=True, caption_file=txt)
        stop.wait(int(env("WATCH_INTERVAL_SECONDS", "15") or 15))
