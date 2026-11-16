import hashlib, html, hmac, os, shutil, threading, time
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, PlainTextResponse
from .config import ROOT, env, log
from .core import (PLATFORMS, JOBS, PUBLIC_FILES, status, create_job, watch_loop, load_jobs, scheduler_loop,
                   parse_local, fmt_local, cancel, reschedule)
from . import settings_store
from .config import BASE_URL
from .platforms import youtube, tiktok, meta, instagram
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .ui import layout, icon, brand, pname, status_badge, state_badge, E

app = FastAPI(title="Social Uploader")
_stop = threading.Event()
from . import auth
from urllib.parse import quote

@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    # OpenShorts calls this endpoint over the private Docker network with a
    # separate bearer token. It deliberately never accepts browser cookies.
    if (path == "/api/internal/publish" or not auth.enabled() or auth.is_public(path)
            or auth.valid_cookie(request.cookies.get(auth.COOKIE))):
        return await call_next(request)
    if path.startswith("/api/") or request.method != "GET":
        return JSONResponse({"detail": "login required"}, status_code=401)
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)

def _safe_next(n): return n if n.startswith("/") and not n.startswith("//") else "/"

def login_page(next_="/", error=""):
    err = f'<div class="note warn" style="margin-bottom:14px">{E(error)}</div>' if error else ""
    return HTMLResponse(f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Social Uploader</title><script>try{{document.documentElement.dataset.theme=localStorage.getItem('theme')||'dark'}}catch(e){{}}</script>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"><link rel="stylesheet" href="/static/app.css"></head>
<body style="display:grid;place-items:center;min-height:100vh;padding:20px"><form method="post" action="/login" class="card" style="width:100%;max-width:380px">
<div class="logo" style="padding:0 0 18px"><div class="logo-mark">{icon("bolt",18)}</div><div><b>Social</b> Uploader</div></div>
<h1 style="font-size:22px;margin-bottom:4px">Welcome back</h1><p class="sub" style="margin-bottom:18px">Enter your app password to continue.</p>{err}
<input type="hidden" name="next" value="{E(_safe_next(next_))}"><div class="field"><label class="f">Password</label><input type="password" name="password" autofocus required autocomplete="current-password"></div>
<button class="btn primary lg" type="submit">Sign in</button><p class="hint" style="text-align:center;margin-top:14px">You'll stay signed in for 30 days on this device.</p></form></body></html>""", status_code=401 if error else 200)

@app.get("/login", response_class=HTMLResponse)
def login_get(next: str = "/"):
    if not auth.enabled(): return RedirectResponse("/", status_code=303)
    return login_page(next)

@app.post("/login")
def login_post(request: Request, password: str = Form(""), next: str = Form("/")):
    if not auth.check_password(password):
        log.warning("Failed login from %s", request.client.host if request.client else "?"); time.sleep(1)
        return login_page(next, "Wrong password.")
    r = RedirectResponse(_safe_next(next), status_code=303)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    r.set_cookie(auth.COOKIE, auth.make_cookie(), max_age=auth.MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return r

@app.get("/logout")
def logout():
    r = RedirectResponse("/login" if auth.enabled() else "/", status_code=303); r.delete_cookie(auth.COOKIE); return r
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

@app.get("/health")
@app.get("/healthz")
def health():
    """Unauthenticated liveness probe; it exposes no account or job data."""
    return {"ok": True}

@app.on_event("startup")
def _startup():
    load_jobs()
    threading.Thread(target=scheduler_loop, args=(_stop,), daemon=True).start(); log.info("Scheduler active")
    if env("WATCH_ENABLED", "true").lower() == "true":
        threading.Thread(target=watch_loop, args=(_stop,), daemon=True).start(); log.info("Watch folder active: %s", ROOT / "inbox")

@app.on_event("shutdown")
def _shutdown(): _stop.set()


def page(title, body, refresh=False, active="", toasts=None, subtitle="", actions=""):
    return HTMLResponse(layout(title, body, active=active, subtitle=subtitle, refresh=refresh, toasts=toasts, actions=actions))

def err_page(title, msg, back="/"):
    return page(title, f'<div class="card empty-state"><div class="big">{icon("x",26)}</div><h3>{E(title)}</h3><p>{E(msg)}</p><a class="btn" href="{back}">Go back</a></div>', toasts=[["bad", msg]])


class InternalPublishRequest(BaseModel):
    """A finished OpenShorts clip, shared locally between containers.

    ``source_path`` is intentionally a path rather than a public URL: the VM
    never has to download its own finished render or expose it before posting.
    """
    source_path: str
    title: str = ""
    caption: str = ""
    platforms: list[str] = Field(default_factory=list)
    public_url: str = ""
    yt_privacy: str | None = None


def _internal_publisher_authorized(authorization: str | None) -> bool:
    expected = env("INTERNAL_PUBLISH_TOKEN")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    return bool(expected and hmac.compare_digest(supplied, expected))


@app.post("/api/internal/publish")
def publish_from_openshorts(payload: InternalPublishRequest,
                            authorization: str | None = Header(default=None)):
    """Queue a render created by OpenShorts, reachable only on the VM network."""
    if not _internal_publisher_authorized(authorization):
        raise HTTPException(status_code=401, detail="invalid internal publisher token")
    allowed_root = Path(env("OPENSHORTS_OUTPUT_DIR", "/shared/openshorts-output")).resolve()
    try:
        source = Path(payload.source_path).resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=404, detail="clip file not found")
    if allowed_root not in source.parents or source.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise HTTPException(status_code=400, detail="clip must be a video inside OPENSHORTS_OUTPUT_DIR")
    platforms = [p for p in payload.platforms if p in PLATFORMS]
    if not platforms:
        raise HTTPException(status_code=400, detail="choose one or more supported platforms")
    jid = create_job(source, payload.title or source.stem, payload.caption, platforms,
                     payload.public_url.strip(), source="openshorts",
                     yt_privacy=payload.yt_privacy if payload.yt_privacy in youtube.VISIBILITY else None)
    log.info("Queued OpenShorts clip %s as publish job %s", source.name, jid)
    return {"job_id": jid, "state": "queued", "status_url": f"/api/internal/jobs/{jid}"}


@app.get("/api/internal/jobs/{jid}")
def internal_job_status(jid: str, authorization: str | None = Header(default=None)):
    if not _internal_publisher_authorized(authorization):
        raise HTTPException(status_code=401, detail="invalid internal publisher token")
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(status_code=404, detail="publish job not found")
    return {"id": job["id"], "state": job["state"], "results": job["results"]}

BCOL = {"youtube": "#ff0033", "tiktok": "#25f4ee", "instagram": "#e1306c", "facebook": "#1877f2"}

@app.get("/", response_class=HTMLResponse)
def index():
    st = status()
    def stl(p): return "Connected" if st[p]["connected"] else ("Missing keys" if not st[p]["configured"] else "Not connected")
    pills = "".join(f'<label class="pill" style="--c:{BCOL[p]}"><input type="checkbox" name="platforms" value="{p}" {"checked" if st[p]["connected"] else ""}>{brand(p,26)}'
                    f'<span class="nm">{pname(p)}<span class="st">{stl(p)}</span></span><span class="chk"></span></label>' for p in PLATFORMS)
    plist = "".join(f'<div class="it">{brand(p,24)}<span class="nm">{pname(p)}</span>{status_badge(st[p])}</div>' for p in PLATFORMS)
    upcoming = sorted([j for j in JOBS.values() if j["state"] == "scheduled"], key=lambda j: j["run_at"])[:3]
    up_html = "".join(f'<div class="it">{icon("clock")}<span class="nm" style="font-weight:500">{E(j["title"])}<small style="display:block" data-ts="{j["run_at"]}">{fmt_local(j["run_at"])}</small></span><span class="icons">{"".join(brand(p,18) for p in j["platforms"])}</span></div>' for j in upcoming) or '<p class="muted" style="margin:0">Nothing scheduled yet.</p>'
    ig_warn = "" if env("PUBLIC_BASE_URL") else '<div class="note warn" style="margin-top:12px">Instagram needs a public URL. Set it in Settings (cloudflared tunnel) or paste one under <i>Advanced</i>.</div>'
    inbox = E(str(ROOT / "inbox"))
    body = f"""<div class="grid g-main"><form id="uploadForm" class="card" action="/upload" method="post" enctype="multipart/form-data">
<div class="field"><div id="drop" class="drop"><input type="file" name="video" accept="video/*">
<div class="empty"><div class="big">{icon("upload",26)}</div><h2>Drop your video here</h2><p class="muted" style="margin:4px 0 0">or click to browse · MP4, MOV, WebM</p></div>
<div class="preview"><video muted playsinline controls></video><div><b id="fname"></b><div class="muted" id="fsize"></div><div class="hint">Click or drop to replace</div><div id="shortsCheck" style="margin-top:6px"></div></div></div></div></div>
<div class="field"><label class="f">Title <span class="muted">· YouTube Shorts &amp; Facebook (#Shorts added automatically)</span></label><input type="text" name="title" maxlength="100" placeholder="My awesome video"></div>
<div class="field"><label class="f">Caption</label><textarea name="caption" placeholder="Say something… #hashtags work everywhere"></textarea></div>
<div class="field"><label class="f">Post to</label><div class="pills">{pills}</div></div>
<div class="field"><label class="f">YouTube Shorts visibility</label><div class="seg">{"".join(f'<label><input type="radio" name="yt_privacy" value="{v}" {"checked" if v == youtube.default_privacy() else ""}>{v.title()}</label>' for v in youtube.VISIBILITY)}</div>
<div class="hint">Facebook, Instagram and TikTok post publicly (TikTok falls back to the most public option your app is allowed).</div></div>
<div class="field"><label class="f">When</label><div class="seg"><label><input type="radio" name="when" value="now" checked>{icon("bolt",16)} Post now</label><label><input type="radio" name="when" value="schedule">{icon("calendar",16)} Schedule</label></div>
<div id="whenAt" class="when-at"><input type="datetime-local" name="run_at"><div class="quick"><button type="button" data-quick="1h">In 1 hour</button><button type="button" data-quick="3h">In 3 hours</button><button type="button" data-quick="0@18">Today 18:00</button><button type="button" data-quick="1@9">Tomorrow 09:00</button><button type="button" data-quick="1@18">Tomorrow 18:00</button></div><div class="hint">Your computer's local time.</div></div></div>
<details style="margin-bottom:18px"><summary class="muted" style="cursor:pointer">Advanced</summary><div class="field" style="margin-top:10px"><label class="f">Public https URL of this video <span class="muted">· Instagram only, optional</span></label><input type="url" name="public_url" placeholder="https://…/video.mp4"></div></details>
<button class="btn primary lg" type="submit">{icon("upload")}<span id="submitTxt">Post now</span></button></form>
<div class="stack"><div class="card"><div class="card-title row between"><h2>Accounts</h2><a class="btn sm" href="/settings">{icon("settings",15)} Manage</a></div><div class="plist">{plist}</div>{ig_warn}</div>
<div class="card"><div class="card-title row between"><h2>Up next</h2><a class="btn sm" href="/scheduled">View all</a></div><div class="plist">{up_html}</div></div>
<div class="card"><div class="card-title">{icon("folder")}<h2>Watch folder</h2></div><p class="muted" style="margin:0 0 8px">Drop <code>video.mp4</code> + optional <code>video.txt</code> (line 1 title, rest caption, optional <code>schedule: 2026-10-25 18:30</code>) into:</p><div class="copy"><code>{inbox}</code><button class="btn sm" type="button" data-copy="{inbox}">{icon("copy",14)}</button></div></div></div></div>"""
    return page("New post", body, active="/", subtitle="Upload once, publish everywhere.")

@app.post("/upload")
async def upload(video: UploadFile = File(...), title: str = Form(""), caption: str = Form(""),
                 platforms: list[str] = Form([]), public_url: str = Form(""),
                 when: str = Form("now"), run_at: str = Form(""), yt_privacy: str = Form("")):
    plats = [p for p in platforms if p in PLATFORMS]
    if not plats: return err_page("Error", "Pick at least one platform.")
    ts = None
    if when == "schedule":
        try: ts = parse_local(run_at)
        except ValueError: return err_page("Error", "Pick a date and time to schedule.")
        if ts <= time.time(): return err_page("Error", "That time is in the past.")
    dest = ROOT / "uploads" / f"{int(time.time())}_{Path(video.filename or 'video.mp4').name}"
    with open(dest, "wb") as f: shutil.copyfileobj(video.file, f)
    jid = create_job(dest, title or Path(video.filename or "video").stem, caption, plats, public_url.strip(), run_at=ts,
                     yt_privacy=yt_privacy if yt_privacy in youtube.VISIBILITY else None)
    return RedirectResponse("/scheduled?t=scheduled" if ts else f"/jobs/{jid}?t=uploaded", status_code=303)

def _progress(j):
    rs = list(j["results"].values()); n = len(rs) or 1
    fin = sum(r["state"] in ("done", "error") for r in rs); errs = sum(r["state"] == "error" for r in rs)
    run = sum(r["state"] == "running" for r in rs)
    pct = int(100 * (fin + .4 * run) / n)
    cls = "ok" if fin == n and not errs else ("err" if errs else "")
    if j["state"] == "finished":
        if not errs: lab = state_badge("done", "All posted")
        elif errs == n: lab = state_badge("error", "Failed")
        else: lab = f'<span class="badge warn"><i></i>{n-errs}/{n} posted</span>'
    else: lab = state_badge(j["state"])
    return pct, cls, lab

def _results(j, big=False):
    out = ""
    for p, r in j["results"].items():
        info = r.get("error") or r.get("url") or r.get("status") or r.get("id") or {"queued": "Waiting…", "running": "Uploading…"}.get(r["state"], "")
        info_h = f'<a href="{E(r["url"])}" target="_blank" rel="noopener">{E(r["url"])}</a>' if r.get("url") else E(str(info))
        vis = f' · {E(r["visibility"])}' if r.get("visibility") else ""
        warn = f'<div class="note warn" style="margin-top:6px;white-space:normal">⚠ {E(r["warning"])}</div>' if r.get("warning") else ""
        badge = '<span class="badge warn"><i></i>Done · check</span>' if r.get("warning") and r["state"] == "done" else state_badge(r["state"])
        out += f'<div class="r" style="flex-wrap:wrap">{brand(p,24)}<div class="x"><div>{pname(p)}{vis}</div><small title="{E(str(info))}">{info_h}</small></div>{badge}{f"<div style=flex-basis:100%>{warn}</div>" if warn else ""}</div>'
    return f'<div class="res{" big" if big else ""}">{out}</div>'

def _src(j): return "Watch folder" if j["source"] == "watch" else "Web upload"

def _job_card(j):
    pct, cls, lab = _progress(j)
    return f"""<div class="job"><div class="job-h"><div class="thumb">{icon("film",20)}</div><div class="t"><a href="/jobs/{j["id"]}">{E(j["title"] or j["file"])}</a><small>{E(j["created"])} · {_src(j)} · {E(j["file"])}</small></div>{lab}</div>
<div class="bar {cls}"><div style="width:{pct}%"></div></div>{_results(j)}</div>"""

@app.get("/jobs/{jid}", response_class=HTMLResponse)
def job_page(jid: str):
    j = JOBS.get(jid)
    if not j: return err_page("Job not found", "This job doesn't exist (anymore).", "/jobs")
    pct, cls, lab = _progress(j)
    when = f'<p class="muted">Scheduled for <b data-ts="{j["run_at"]}">{fmt_local(j["run_at"])}</b></p>' if j["state"] == "scheduled" else ""
    body = f"""<div class="grid g-main"><div class="card"><div class="row between"><h2>Progress</h2>{lab}</div><div class="bar {cls}"><div style="width:{pct}%"></div></div>{when}{_results(j, big=True)}</div>
<div class="card"><h2 style="margin-bottom:14px">Details</h2><div class="field"><label class="f">File</label><code>{E(j["file"])}</code></div>
<div class="field"><label class="f">Created</label><span class="muted">{E(j["created"])} · {_src(j)}</span></div>
<div class="field"><label class="f">Caption</label><div class="note" style="white-space:pre-wrap">{E(j.get("caption") or "—")}</div></div></div></div>"""
    return page(E(j["title"] or j["file"]), body, active="/jobs", subtitle=f"Job {E(jid)}",
                refresh=j["state"] in ("queued", "running"), actions='<a class="btn" href="/jobs">All jobs</a>')

@app.get("/jobs", response_class=HTMLResponse)
def jobs():
    js = sorted([j for j in JOBS.values() if j["state"] not in ("scheduled", "cancelled")], key=lambda j: j["created"], reverse=True)
    body = f'<div class="jobs">{"".join(_job_card(j) for j in js)}</div>' if js else f'<div class="card empty-state"><div class="big">{icon("list",26)}</div><h3>No posts yet</h3><p>Your upload history will appear here.</p><a class="btn primary" href="/">Create a post</a></div>'
    return page("Jobs", body, active="/jobs", subtitle="Upload history and live progress.",
                refresh=any(j["state"] in ("queued", "running") for j in JOBS.values()), actions=f'<a class="btn primary" href="/">{icon("upload",16)} New post</a>')

@app.get("/api/status")
def api_status(): return JSONResponse({"platforms": status(), "jobs": list(JOBS.values())})

NEXT = {"youtube": "YouTube Shorts saved – now click Connect on the YouTube Shorts card.", "tiktok": "TikTok saved – now click Connect on the TikTok card.",
        "meta": "Meta saved – now click Connect on the Facebook card (also links Instagram).",
        "instagram": "Instagram saved – now click Connect on the Instagram card (log in as your professional account).", "watch": "Watch folder platforms updated."}
CARDS = [("youtube", "YouTube Shorts", ["youtube"], "youtube", "Google OAuth · Data API v3 · vertical, ≤ 3 min, #Shorts added"),
         ("tiktok", "TikTok", ["tiktok"], "tiktok", "Content Posting API"),
         ("facebook", "Facebook Page", ["meta"], "meta", "Graph API · Page videos"),
         ("instagram", "Instagram Reels", ["instagram"], "instagram", "Instagram API with Instagram Login · no Facebook Page needed")]
REDIR = {"instagram": instagram.redirect_uri, "youtube": lambda: youtube.REDIRECT, "tiktok": lambda: tiktok.REDIRECT, "meta": lambda: meta.REDIRECT}

def _field(key, label, secret, val):
    if key == "YOUTUBE_PRIVACY":
        cur = val if val in youtube.VISIBILITY else "public"
        opts = "".join(f'<label><input type="radio" name="{key}" value="{v}" {"checked" if v == cur else ""}>{v.title()}</label>' for v in youtube.VISIBILITY)
        return f'<div class="field" style="grid-column:1/-1"><label class="f">{E(label)}</label><div class="seg">{opts}</div><div class="hint"><code>{key}</code> · unverified API projects get forced to private by YouTube</div></div>'
    if secret: inp = f'<input type="password" name="{key}" placeholder="{E(settings_store.mask(val) or "Not set")}" autocomplete="new-password">'
    else: inp = f'<input type="text" name="{key}" value="{E(val)}" placeholder="Not set">'
    return f'<div class="field"><label class="f">{E(label)}</label>{inp}<div class="hint"><code>{key}</code></div></div>'

def settings(toasts=None, open_=None):
    st = status(); cur = settings_store.current(); cards = ""
    first_missing = next((c[0] for c in CARDS if not st[c[0]]["connected"]), None)
    for cid, title, groups, oauth, sub in CARDS:
        s = st[cid]
        fields = "".join(_field(k, l, sec, cur.get(k, "")) for k, l, sec, g in settings_store.FIELDS if g in groups)
        extra = {"youtube": '<div class="field"><label class="f">…or upload <code>client_secret.json</code></label><input class="file-in" type="file" name="client_json" accept=".json"></div>',
                 "instagram": (f'<div class="note" style="margin-bottom:8px">Connected as <b>@{E(instagram.username() or "?")}</b> via {"pasted access token" if instagram.manual_set() else "Instagram Login"}.</div>' if instagram.connected() else "") + '<div class="note">Works with an Instagram professional (Business/Creator) account – no Facebook Page needed. Either Save app ID + secret and click Connect, <b>or</b> just paste an existing long-lived access token + user ID (no app secret needed). Instagram downloads the video from a public https URL, so set <code>PUBLIC_BASE_URL</code> to a tunnel (e.g. <code>cloudflared tunnel --url http://localhost:8000</code>). If Meta rejects the http://localhost redirect, set <code>BASE_URL</code> to your https tunnel too and register that redirect URI. Fallback: an IG account linked to a Facebook Page (Facebook card) still works.</div>',
                 "tiktok": f'<div class="note">Posts use <code>{E(env("TIKTOK_PRIVACY","PUBLIC_TO_EVERYONE") or "PUBLIC_TO_EVERYONE")}</code> when your account allows it. Unaudited apps can only post privately (SELF_ONLY) – you\'ll see a warning on the job.</div>',
                 "facebook": ""}[cid]
        uri = REDIR[oauth]()
        connect = (f'<a class="btn" href="/connect/{oauth}">{icon("link",15)} {"Reconnect" if s["connected"] else "Connect"}</a>' if s["configured"]
                   else f'<button class="btn" type="button" disabled title="Save keys first">{icon("link",15)} Connect</button>')
        is_open = "open" if (open_ and cid in open_) or (not open_ and cid == first_missing) else ""
        cards += f"""<details class="acc" {is_open}><summary>{brand(cid,34)}<div class="nm"><h2>{title}</h2><small>{sub}</small></div>{status_badge(s)}<span class="chev">{icon("chevron")}</span></summary>
<div class="body"><label class="f" style="margin-top:16px">Redirect URI <span class="muted">· paste into the developer console</span></label><div class="copy"><code>{E(uri)}</code><button class="btn sm" type="button" data-copy="{E(uri)}">{icon("copy",14)} Copy</button></div>
<div class="fields">{fields}</div>{extra}<div class="row" style="margin-top:16px"><button class="btn primary" type="submit" name="_card" value="{cid}">Save</button>{connect}</div></div></details>"""
    watch = "".join(_field(k, l, sec, cur.get(k, "")) for k, l, sec, g in settings_store.FIELDS if g == "watch")
    cards += f"""<details class="acc" {"open" if open_ and "watch" in open_ else ""}><summary><div class="logo-mark" style="background:var(--accsoft);color:var(--acc);box-shadow:none">{icon("folder")}</div><div class="nm"><h2>Watch folder</h2><small>Auto-post files dropped into ./inbox</small></div><span class="chev">{icon("chevron")}</span></summary>
<div class="body"><div class="fields" style="grid-template-columns:1fr">{watch}</div><button class="btn primary" type="submit" name="_card" value="watch">Save</button></div></details>"""
    pub = env("PUBLIC_BASE_URL")
    pub_card = f"""<div class="card" style="margin-bottom:18px"><div class="row between"><div><h2>Public URL</h2><small>{"Reachable from the internet (tunnel)" if pub else "Not set – Instagram needs one. On the VM, start-always.sh fills it in."}</small></div>
{'<span class="badge ok"><i></i>Online</span>' if pub else '<span class="badge warn"><i></i>Not set</span>'}</div>
{f'<div class="copy" style="margin-top:12px"><code>{E(pub)}</code><button class="btn sm" type="button" data-copy="{E(pub)}">{icon("copy",14)} Copy</button><a class="btn sm" href="{E(pub)}" target="_blank" rel="noopener">{icon("link",14)} Open</a></div>' if pub else ''}
<div class="hint">App base URL: <code>{E(env("BASE_URL","http://localhost:8000"))}</code> · Password protection: {"on" if auth.enabled() else "off (set APP_PASSWORD)"}{' · <a href="/logout">Sign out</a>' if auth.enabled() else ''}</div></div>"""
    body = f"""{pub_card}<form method="post" action="/settings" enctype="multipart/form-data" class="stack" autocomplete="off">{cards}</form>
<p class="muted" style="margin-top:18px">Secret fields show only the last 4 characters; leave a field blank to keep it. Saved to <code>.env</code> and applied instantly. Delete a file in <code>tokens/</code> to disconnect.</p>"""
    return page("Settings", body, active="/settings", subtitle="Connect your accounts. Keys stay on this computer.", toasts=toasts)

@app.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    up = form.get("client_json"); data = await up.read() if up is not None and hasattr(up, "read") else b""
    card = str(form.get("_card") or "")
    try:
        changed = settings_store.save({k: str(form.get(k) or "") for k in settings_store.KEYS}, BASE_URL, data or None)
    except Exception as e:
        return settings([["bad", f"Save failed: {e}"]], {card})
    plats = {f[3] for f in settings_store.FIELDS if f[0] in changed}
    if "client_secret.json" in changed: plats.add("youtube")
    toasts = [["ok", NEXT[p]] for p in ["youtube", "tiktok", "meta", "instagram", "watch"] if p in plats and not (p == "instagram" and {"INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"} & set(changed))]
    if {"INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"} & set(changed) and instagram.manual_set():
        try:
            t = instagram.seed_manual()
            toasts.append(["ok", f"Instagram connected as @{t['username']}" + (" (token refreshed for 60 days)" if t.get("expires_at") else "")])
            if t.get("warning"): toasts.append(["bad", t["warning"]])
        except Exception as e: toasts.append(["bad", f"Instagram token check failed: {e}"])
    toasts = toasts or [["info", "No changes – blank fields keep their value."]]
    log.info("Settings saved: %s", ", ".join(changed) or "none")
    return settings(toasts, {card})

@app.get("/settings", response_class=HTMLResponse)
def settings_get(): return settings()

@app.get("/scheduled", response_class=HTMLResponse)
def scheduled():
    js = sorted([j for j in JOBS.values() if j["state"] in ("scheduled", "cancelled")], key=lambda j: (j["state"] != "scheduled", j.get("run_at") or 0))
    rows = ""
    for j in js:
        d = datetime.fromtimestamp(j["run_at"]) if j.get("run_at") else datetime.now()
        cancel_b = f'<form method="post" action="/scheduled/{j["id"]}/cancel"><button class="btn sm danger">{icon("x",14)} Cancel</button></form>' if j["state"] == "scheduled" else ""
        rows += f"""<tr><td><div class="when"><div class="d"><span>{d.strftime("%b")}</span><b>{d.strftime("%d")}</b></div><div><b>{d.strftime("%H:%M")}</b><small style="display:block">{d.strftime("%A")}</small></div></div></td>
<td><a href="/jobs/{j["id"]}" style="color:var(--text);font-weight:600">{E(j["title"])}</a><small style="display:block">{E(j["file"])}</small></td>
<td><div class="icons">{"".join(brand(p,22) for p in j["platforms"])}</div></td><td>{state_badge(j["state"])}</td>
<td><div class="inline-form"><form class="inline-form" method="post" action="/scheduled/{j["id"]}/reschedule"><input type="datetime-local" name="run_at" value="{d.strftime("%Y-%m-%dT%H:%M")}" required><button class="btn sm">{icon("clock",14)} {"Reschedule" if j["state"]=="scheduled" else "Restore"}</button></form>{cancel_b}</div></td></tr>"""
    if js:
        body = (f'<div class="card"><div class="tbl-wrap"><table class="t"><tr><th>When</th><th>Post</th><th>Platforms</th><th>Status</th><th>Actions</th></tr>{rows}</table></div></div>'
                '<p class="muted" style="margin-top:14px">Times are your computer\'s local time. The app checks every 20 s while running; if it was off, due posts go out as soon as it starts.</p>')
    else:
        body = f'<div class="card empty-state"><div class="big">{icon("calendar",26)}</div><h3>Nothing scheduled</h3><p>Choose <b>Schedule</b> when creating a post.</p><a class="btn primary" href="/">Schedule a post</a></div>'
    return page("Scheduled", body, active="/scheduled", subtitle="Upcoming posts – cancel or move them anytime.", actions=f'<a class="btn primary" href="/">{icon("calendar",16)} New scheduled post</a>')

@app.post("/scheduled/{jid}/cancel")
def sched_cancel(jid: str):
    cancel(jid); return RedirectResponse("/scheduled?t=cancelled", status_code=303)

@app.post("/scheduled/{jid}/reschedule")
def sched_resched(jid: str, run_at: str = Form(...)):
    try:
        ts = parse_local(run_at)
        if ts <= time.time(): raise ValueError
        reschedule(jid, ts)
    except ValueError: return RedirectResponse("/scheduled?t=badtime", status_code=303)
    return RedirectResponse("/scheduled?t=rescheduled", status_code=303)

@app.get("/connect/{name}")
def connect(name: str):
    try:
        url = {"instagram": instagram.auth_url, "youtube": youtube.auth_url, "tiktok": tiktok.auth_url, "meta": meta.auth_url}[name]()
        return RedirectResponse(url)
    except Exception as e:
        log.exception("connect %s", name); return err_page("Connect error", str(e), "/settings")

@app.get("/oauth/{name}/callback")
def oauth_cb(name: str, request: Request, code: str = "", state: str = "", error: str = ""):
    try:
        if error: raise RuntimeError(error)
        if name == "youtube": youtube.callback(str(request.url))
        elif name == "tiktok": tiktok.callback(code, state)
        elif name == "meta": meta.callback(code, state)
        elif name == "instagram": instagram.callback(code, state)
        log.info("Connected %s", name); return RedirectResponse("/settings?t=connected")
    except Exception as e:
        log.exception("oauth %s", name); return err_page("Connect failed", str(e), "/settings")

@app.get("/media/{token}/{name}")
def media(token: str, name: str):
    p = PUBLIC_FILES.get(token)   # only files currently being posted to Instagram, via unguessable token
    if not p or not p.exists(): return PlainTextResponse("not found", 404)
    return FileResponse(p, media_type="video/mp4")

@app.get("/logs", response_class=HTMLResponse)
def logs():
    import re
    f = ROOT / "logs" / "app.log"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if f.exists() else []
    out = []
    for ln in lines:
        m = re.match(r"(\S+ \S+) (\w+) (.*)", ln)
        out.append(f'<span class="l-{m.group(2)}"><span class="ts">{E(m.group(1))}</span> <span class="lv">{E(m.group(2))}</span> {E(m.group(3))}</span>' if m else E(ln))
    body = f'<pre class="log">{chr(10).join(out) or "No log entries yet."}</pre>'
    return page("Logs", body, active="/logs", subtitle="Last 300 lines of logs/app.log · refreshes every few seconds", refresh=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=env("HOST") or env("APP_HOST", "127.0.0.1"), port=int(env("PORT") or env("APP_PORT", "8000")))
