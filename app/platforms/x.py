"""X (Twitter) API v2: OAuth 2.0 + PKCE, chunked media upload, then create a post."""
import base64, hashlib, mimetypes, secrets, time, urllib.parse, requests
from pathlib import Path
from ..config import env, load_token, save_token, log

AUTH = "https://x.com/i/oauth2/authorize"
TOKEN = "https://api.x.com/2/oauth2/token"
ME = "https://api.x.com/2/users/me"
INIT = "https://api.x.com/2/media/upload/initialize"
APPEND = "https://api.x.com/2/media/upload/{id}/append"
FINALIZE = "https://api.x.com/2/media/upload/{id}/finalize"
STATUS = "https://api.x.com/2/media/upload"
TWEETS = "https://api.x.com/2/tweets"
SCOPES = "tweet.read tweet.write users.read media.write offline.access"
# Stay under the documented 5 MB recommendation (server max is 8 MB).
CHUNK = 4 * 1024 * 1024
RETRY_STATUS = {500, 502, 503, 504}
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
_state = {}

def redirect_uri():
    return f'{env("BASE_URL", "http://localhost:8000").rstrip("/")}/oauth/x/callback'

def configured():
    return bool(env("X_CLIENT_ID"))

def connected():
    t = load_token("x")
    return bool(t and t.get("access_token"))

def username():
    return (load_token("x") or {}).get("username", "")

def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge

def auth_url():
    if not configured():
        raise RuntimeError("X_CLIENT_ID is not set. Add your X Client ID in Settings (or as X_CLIENT_ID), Save, then Connect.")
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    _state.update(s=state, verifier=verifier)
    q = {"response_type": "code", "client_id": env("X_CLIENT_ID"), "redirect_uri": redirect_uri(),
         "scope": SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return AUTH + "?" + urllib.parse.urlencode(q)

def _token_auth():
    """Confidential apps send Basic auth; public clients send client_id in the body only."""
    cid, sec = env("X_CLIENT_ID"), env("X_CLIENT_SECRET")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"client_id": cid}
    if sec:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()
    return headers, data

def _save_token(d):
    if "access_token" not in d:
        raise RuntimeError(f"X token error: {d}")
    prev = load_token("x") or {}
    out = {**prev, **d}
    if d.get("expires_in") is not None:
        out["expires_at"] = time.time() + int(d.get("expires_in", 0)) - 60
    if not d.get("refresh_token") and prev.get("refresh_token"):
        out["refresh_token"] = prev["refresh_token"]
    save_token("x", out)
    return out

def _check(r, what):
    try:
        d = r.json()
    except ValueError:
        d = {"raw": r.text}
    if r.status_code >= 400 or d.get("errors") or d.get("error"):
        err = d.get("error_description") or d.get("detail") or d.get("error") or d.get("errors") or d
        raise RuntimeError(f"X {what}: {err}")
    return d

def _request(method, url, tries=6, timeout=60, **kwargs):
    last = None
    for i in range(tries):
        try:
            r = requests.request(method, url, timeout=timeout, **kwargs)
            if r.status_code in RETRY_STATUS and i < tries - 1:
                last = r; time.sleep(min(2 ** i, 16)); continue
            return r
        except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, OSError) as e:
            last = e
            if i == tries - 1: raise
            time.sleep(min(2 ** i, 16))
    return last

def callback(code, state):
    if state != _state.get("s"): raise RuntimeError("bad OAuth state")
    verifier = _state.get("verifier")
    if not verifier: raise RuntimeError("missing PKCE verifier – click Connect again")
    headers, data = _token_auth()
    data.update(code=code, grant_type="authorization_code", redirect_uri=redirect_uri(), code_verifier=verifier)
    tok = _save_token(_check(_request("POST", TOKEN, headers=headers, data=data, timeout=30), "code exchange"))
    try:
        me = _check(_request("GET", ME, headers=_bearer(tok["access_token"]), timeout=30), "profile")
        user = me.get("data") or me
        tok.update(user_id=str(user.get("id") or ""), username=user.get("username") or "", name=user.get("name") or "")
        save_token("x", tok)
    except Exception as e:
        log.warning("X profile lookup failed: %s", e)
    log.info("X connected as @%s", tok.get("username") or "?")
    return tok

def _bearer(token):
    return {"Authorization": f"Bearer {token}"}

def access_token():
    t = load_token("x")
    if not t or not t.get("access_token"):
        raise RuntimeError("X not connected – Settings → X → Connect")
    if time.time() > t.get("expires_at", 0):
        if not t.get("refresh_token"):
            raise RuntimeError("X login expired – reconnect in Settings")
        headers, data = _token_auth()
        data.update(grant_type="refresh_token", refresh_token=t["refresh_token"])
        t = _save_token(_check(_request("POST", TOKEN, headers=headers, data=data, timeout=30), "token refresh"))
        log.info("X token refreshed")
    return t["access_token"]

def tweet_text(title="", caption="", limit=280):
    """Post text: caption if present, otherwise title. Truncate at a word boundary when possible."""
    text = (caption or "").strip() or (title or "").strip()
    if len(text) <= limit: return text
    body = text[: limit - 1]
    sp = body.rfind(" ")
    if sp >= limit // 2: body = body[:sp]
    return body.rstrip() + "…"

def media_type(path: Path):
    ext = path.suffix.lower()
    if ext in MIME: return MIME[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "video/mp4"

def _processing(d):
    return (d.get("data") or d).get("processing_info") or {}

def _media_id(d):
    data = d.get("data") or d
    mid = data.get("id") or data.get("media_id") or data.get("media_id_string")
    if not mid: raise RuntimeError(f"X media upload: no id in {d}")
    return str(mid)

def _wait_until_ready(mid, headers, poll=None, tries=120):
    info = poll or {}
    for _ in range(tries):
        state = (info.get("state") or "succeeded").lower()
        if state == "succeeded": return
        if state == "failed":
            err = (info.get("error") or info)
            raise RuntimeError(f"X media processing failed: {err}")
        time.sleep(int(info.get("check_after_secs") or 2))
        d = _check(_request("GET", STATUS, headers=headers, params={"command": "STATUS", "media_id": mid}, timeout=30), "media status")
        info = _processing(d) or {"state": "succeeded"}
        log.info("X media %s: %s", mid, info.get("state"))
    else:
        raise RuntimeError("X media processing timed out")

def upload(path: Path, title: str, caption: str):
    tok = access_token()
    headers = _bearer(tok)
    path = Path(path)
    size = path.stat().st_size
    typ = media_type(path)
    init = _check(_request("POST", INIT, headers={**headers, "Content-Type": "application/json"},
                           json={"media_type": typ, "total_bytes": size, "media_category": "tweet_video"}, timeout=60),
                  "media initialize")
    mid = _media_id(init)
    with open(path, "rb") as f:
        idx = 0
        while True:
            chunk = f.read(CHUNK)
            if not chunk: break
            r = _request("POST", APPEND.format(id=mid), headers=headers, data={"segment_index": idx},
                         files={"media": (path.name, chunk, typ)}, timeout=300)
            _check(r, f"media append {idx}")
            idx += 1
    if idx == 0:
        raise RuntimeError("X upload: file is empty")
    fin = _check(_request("POST", FINALIZE.format(id=mid), headers=headers, timeout=60), "media finalize")
    _wait_until_ready(mid, headers, poll=_processing(fin))
    body = {"media": {"media_ids": [mid]}}
    text = tweet_text(title, caption)
    if text: body["text"] = text
    tw = _check(_request("POST", TWEETS, headers={**headers, "Content-Type": "application/json"}, json=body, timeout=60), "create post")
    data = tw.get("data") or tw
    tid = str(data.get("id") or "")
    out = {"id": tid, "media_id": mid, "visibility": "public"}
    if tid: out["url"] = f"https://x.com/i/web/status/{tid}"
    return out
