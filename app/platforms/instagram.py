"""Instagram API with Instagram Login (business login) – no Facebook Page needed.
Docs: developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login"""
import time, secrets, urllib.parse, requests
from pathlib import Path
from ..config import env, load_token, save_token, log

AUTH = "https://www.instagram.com/oauth/authorize"
TOKEN = "https://api.instagram.com/oauth/access_token"
GRAPH_ROOT = "https://graph.instagram.com"          # token endpoints (unversioned)
API_VERSION = "v26.0"
GRAPH = f"{GRAPH_ROOT}/{API_VERSION}"                 # media / me / publish
SCOPES = "instagram_business_basic,instagram_business_content_publish"
_state = {}

def redirect_uri():   # read live so BASE_URL can be switched to an https tunnel without restart
    return f'{env("BASE_URL", "http://localhost:8000").rstrip("/")}/oauth/instagram/callback'

def manual_set(): return bool(env("INSTAGRAM_ACCESS_TOKEN") and env("INSTAGRAM_USER_ID"))
def configured(): return bool(env("INSTAGRAM_APP_ID") and env("INSTAGRAM_APP_SECRET")) or manual_set()
def connected():
    t = load_token("instagram"); return bool(t and t.get("access_token") and t.get("user_id")) or manual_set()

def validate(token):
    """GET /me – returns {'user_id','username'} or raises."""
    return _check(requests.get(f"{GRAPH}/me", params={"fields": "user_id,username", "access_token": token}, timeout=30), "token check")

def _refresh(token):
    return _check(requests.get(f"{GRAPH_ROOT}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30), "token refresh")

def seed_manual(now=None):
    """Called after saving INSTAGRAM_ACCESS_TOKEN/USER_ID: validate, try one refresh, store in tokens/instagram.json."""
    now = now or time.time(); tok, uid = env("INSTAGRAM_ACCESS_TOKEN"), env("INSTAGRAM_USER_ID")
    me = validate(tok)
    t = {"access_token": tok, "user_id": uid or str(me.get("user_id")), "username": me.get("username", ""), "source": "manual",
         "orig": tok, "issued_at": now, "expires_at": None, "next_refresh": now}
    try:   # works if the token is >24 h old; gives us a fresh 60-day token and a known expiry
        d = _refresh(tok); t.update(access_token=d["access_token"], expires_at=now + int(d.get("expires_in", 5184000)), next_refresh=None)
    except Exception as e: log.info("Instagram manual token not refreshed yet (%s); will retry daily", e); t["next_refresh"] = now + 86400
    if uid and str(me.get("user_id")) not in ("None", uid):
        t["warning"] = f"/me returned user_id {me.get('user_id')} but INSTAGRAM_USER_ID is {uid}; using {uid}"
    save_token("instagram", t); return t
def username(): return (load_token("instagram") or {}).get("username", "")

def auth_url():
    s = secrets.token_urlsafe(16); _state["s"] = s
    return AUTH + "?" + urllib.parse.urlencode({"enable_fb_login": "0", "force_authentication": "1",
        "client_id": env("INSTAGRAM_APP_ID"), "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPES, "state": s})

def _check(r, what):
    try: d = r.json()
    except ValueError: d = {"raw": r.text}
    if r.status_code >= 400 or "error" in d or "error_message" in d:
        raise RuntimeError(f"Instagram {what}: {d.get('error_message') or d.get('error') or d}")
    return d

def callback(code, state):
    if state != _state.get("s"): raise RuntimeError("bad OAuth state")
    code = code.split("#_")[0]   # Instagram appends '#_' to the code
    short = _check(requests.post(TOKEN, data={"client_id": env("INSTAGRAM_APP_ID"), "client_secret": env("INSTAGRAM_APP_SECRET"),
        "grant_type": "authorization_code", "redirect_uri": redirect_uri(), "code": code}, timeout=30), "code exchange")
    long = _check(requests.get(f"{GRAPH_ROOT}/access_token", params={"grant_type": "ig_exchange_token",
        "client_secret": env("INSTAGRAM_APP_SECRET"), "access_token": short["access_token"]}, timeout=30), "long-lived token")
    me = _check(requests.get(f"{GRAPH}/me", params={"fields": "user_id,username,account_type", "access_token": long["access_token"]}, timeout=30), "profile")
    tok = {"access_token": long["access_token"], "expires_at": time.time() + int(long.get("expires_in", 5184000)),
           "issued_at": time.time(), "user_id": str(me.get("user_id") or me.get("id")), "username": me.get("username", ""),
           "account_type": me.get("account_type", "")}
    save_token("instagram", tok); log.info("Instagram connected as @%s", tok["username"]); return tok

def access_token(now=None):
    """Long-lived tokens last 60 days; refresh when <10 days left (allowed once the token is >24 h old)."""
    t = load_token("instagram"); now = now or time.time()
    if manual_set() and (not t or (t.get("source") == "manual" and t.get("orig") != env("INSTAGRAM_ACCESS_TOKEN"))
                         or (t.get("source") != "manual" and not t.get("access_token"))):
        # token pasted into .env (or changed) – adopt it without validation round-trip
        t = {"access_token": env("INSTAGRAM_ACCESS_TOKEN"), "user_id": env("INSTAGRAM_USER_ID"), "source": "manual",
             "orig": env("INSTAGRAM_ACCESS_TOKEN"), "issued_at": now, "expires_at": None, "next_refresh": now}
        save_token("instagram", t)
    if not t: raise RuntimeError("Instagram not connected – Settings → Instagram → Connect or paste an access token")
    if t.get("source") == "manual" and env("INSTAGRAM_USER_ID"): t["user_id"] = env("INSTAGRAM_USER_ID")
    due = (t.get("expires_at") and t["expires_at"] - now < 10 * 86400 and now - t.get("issued_at", 0) > 86400) or \
          (t.get("expires_at") is None and now >= (t.get("next_refresh") or 0))
    if due:
        try:
            d = _refresh(t["access_token"])
            t.update(access_token=d["access_token"], expires_at=now + int(d.get("expires_in", 5184000)), issued_at=now, next_refresh=None)
            log.info("Instagram token refreshed")
        except Exception as e:
            if t.get("source") != "manual" and t.get("expires_at") and t["expires_at"] < now: raise
            log.warning("Instagram token refresh failed (%s); using current token", e); t["next_refresh"] = now + 86400
        save_token("instagram", t)
    return t["access_token"], t["user_id"]

def container_params(video_url, caption, token):
    return {"media_type": "REELS", "video_url": video_url, "caption": caption or "", "share_to_feed": "true", "access_token": token}

def upload(path: Path, title: str, caption: str, public_url: str, poll=5, tries=120):
    tok, uid = access_token()
    if not public_url.startswith("https://"):
        raise RuntimeError("Instagram needs a public https URL to fetch the video – set PUBLIC_BASE_URL (cloudflared/ngrok tunnel) in Settings")
    cid = _check(requests.post(f"{GRAPH}/{uid}/media", data=container_params(public_url, caption, tok), timeout=60), "create container")["id"]
    for _ in range(tries):
        s = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": tok}, timeout=30), "status")
        log.info("Instagram container %s: %s", cid, s.get("status_code"))
        if s.get("status_code") in ("FINISHED", "PUBLISHED"): break
        if s.get("status_code") in ("ERROR", "EXPIRED"): raise RuntimeError(f"Instagram processing failed: {s.get('status') or s}")
        time.sleep(poll)
    else: raise RuntimeError("Instagram processing timed out")
    mid = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=60), "publish")["id"]
    out = {"id": mid, "visibility": "public"}
    try:
        pl = requests.get(f"{GRAPH}/{mid}", params={"fields": "permalink", "access_token": tok}, timeout=30).json().get("permalink")
        if pl: out["url"] = pl
    except Exception: pass
    return out
