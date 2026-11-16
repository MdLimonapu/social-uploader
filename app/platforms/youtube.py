"""YouTube Data API v3 resumable upload with OAuth + token caching."""
import os
from pathlib import Path
from ..config import ROOT, BASE_URL, env, TOKENS, log

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # allow http://localhost callback
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = TOKENS / "youtube.json"
REDIRECT = f"{BASE_URL}/oauth/youtube/callback"
_state = {}

def secret_file():
    return ROOT / env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")

def configured():
    return secret_file().exists()

def _flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(str(secret_file()), scopes=SCOPES, redirect_uri=REDIRECT)

def auth_url():
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    _state["verifier"] = getattr(flow, "code_verifier", None)
    return url

def callback(full_url):
    flow = _flow()
    if _state.get("verifier"):
        flow.code_verifier = _state["verifier"]
    flow.fetch_token(authorization_response=full_url)
    TOKEN_FILE.write_text(flow.credentials.to_json())

def credentials():
    if not TOKEN_FILE.exists():
        return None
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); TOKEN_FILE.write_text(creds.to_json())
    return creds

def connected():
    return TOKEN_FILE.exists()

VISIBILITY = ("public", "unlisted", "private")
FORCED_PRIVATE_WARNING = ("YouTube forced this video to PRIVATE because your Google Cloud API project is unverified. "
    "Request a YouTube API audit/verification (YouTube API Services – Audit and Quota Extension form) to post publicly; "
    "until then you can switch it to Public by hand in YouTube Studio.")

def default_privacy():
    v = env("YOUTUBE_PRIVACY", "public").lower()
    return v if v in VISIBILITY else "public"

def check_forced_private(requested, actual):
    return FORCED_PRIVATE_WARNING if requested in ("public", "unlisted") and actual == "private" else None

def parse_tags(tags) -> list[str]:
    """'a, b,#c' or ['a','b'] -> ['a','b','c'] (YouTube allows ~500 chars of tags in total)."""
    if isinstance(tags, str): tags = tags.replace("\n", ",").split(",")
    out, total = [], 0
    for t in tags or []:
        t = str(t).strip().lstrip("#").replace("<", "").replace(">", "").strip()
        if not t or t in out: continue
        if total + len(t) + 1 > 500: break
        out.append(t); total += len(t) + 1
    return out

def build_body(title, caption, privacy=None, shorts=True, tags=None):
    """shorts=True: Shorts upload (#Shorts added). shorts=False: normal long-form video, title/description untouched."""
    if shorts:
        from .shorts import tag_title, tag_description
        t, d = tag_title(title), tag_description(caption)
    else:
        t, d = ((title or "Untitled").strip() or "Untitled")[:100], (caption or "").strip()[:5000]
    snippet = {"title": t, "description": d, "categoryId": "22"}
    if tags and (tl := parse_tags(tags)): snippet["tags"] = tl
    return {"snippet": snippet,
            "status": {"privacyStatus": privacy if privacy in VISIBILITY else default_privacy(), "selfDeclaredMadeForKids": False}}

RETRY_STATUS = {500, 502, 503, 504}

def _next_chunk(req, tries=6):
    """One resumable-upload step with retries on transient errors (the upload resumes where it stopped)."""
    import time
    from googleapiclient.errors import HttpError
    for i in range(tries):
        try: return req.next_chunk()
        except HttpError as e:
            if getattr(e.resp, "status", None) not in RETRY_STATUS or i == tries - 1: raise
            err = e
        except (ConnectionError, TimeoutError, OSError) as e:
            if i == tries - 1: raise
            err = e
        log.warning("YouTube chunk failed (%s), retrying in %ss", err, 2 ** i); time.sleep(2 ** i)

def upload(path: Path, title: str, caption: str, privacy: str | None = None, shorts: bool = True, tags=None):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    if shorts:
        from .shorts import check_short
        ok, msg = check_short(path)
        if not ok: raise RuntimeError(msg)
        if msg.startswith("warning"): log.warning("YouTube Shorts: %s", msg)
    creds = credentials()
    if not creds:
        raise RuntimeError("YouTube not connected")
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    # Resumable upload streamed from disk in 8 MB chunks: RAM use stays small even for multi-GB videos.
    media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=(body := build_body(title, caption, privacy, shorts, tags)), media_body=media)
    resp = None
    while resp is None:
        status, resp = _next_chunk(req)
        if status:
            log.info("YouTube upload %d%%", int(status.progress() * 100))
    vid = resp["id"]; requested = body["status"]["privacyStatus"]
    actual = (resp.get("status") or {}).get("privacyStatus")
    try:  # re-read: YouTube may lock unverified uploads to private after processing starts
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if items: actual = items[0]["status"].get("privacyStatus", actual)
    except Exception as e: log.warning("YouTube status check failed: %s", e)
    out = {"id": vid, "url": f"https://youtube.com/shorts/{vid}" if shorts else f"https://www.youtube.com/watch?v={vid}", "visibility": actual or requested}
    w = check_forced_private(requested, actual)
    if w: out["warning"] = w; log.warning("YouTube %s: %s", vid, w)
    return out
