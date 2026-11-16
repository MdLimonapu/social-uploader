"""Facebook Page video + Instagram Reels via Graph API."""
import time, secrets, urllib.parse, requests
from pathlib import Path
from ..config import BASE_URL, GRAPH, env, load_token, save_token, log

REDIRECT = f"{BASE_URL}/oauth/meta/callback"
SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish,business_management"
_state = {}

def _tok():
    t = load_token("meta") or {}
    return {"page_id": t.get("page_id") or env("FB_PAGE_ID"),
            "page_token": t.get("page_token") or env("FB_PAGE_ACCESS_TOKEN"),
            "ig_user_id": t.get("ig_user_id") or env("IG_USER_ID")}

def configured(): return bool(env("FB_APP_ID") and env("FB_APP_SECRET")) or bool(env("FB_PAGE_ACCESS_TOKEN"))
def fb_connected(): t = _tok(); return bool(t["page_id"] and t["page_token"])
def ig_connected(): t = _tok(); return bool(t["ig_user_id"] and t["page_token"])

def auth_url():
    s = secrets.token_urlsafe(16); _state["s"] = s
    return "https://www.facebook.com/" + GRAPH.rsplit("/", 1)[1] + "/dialog/oauth?" + urllib.parse.urlencode(
        {"client_id": env("FB_APP_ID"), "redirect_uri": REDIRECT, "state": s, "scope": SCOPES})

def callback(code, state):
    if state != _state.get("s"): raise RuntimeError("bad OAuth state")
    a, sec = env("FB_APP_ID"), env("FB_APP_SECRET")
    short = requests.get(f"{GRAPH}/oauth/access_token", params={"client_id": a, "client_secret": sec, "redirect_uri": REDIRECT, "code": code}, timeout=30).json()
    long = requests.get(f"{GRAPH}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": a, "client_secret": sec, "fb_exchange_token": short["access_token"]}, timeout=30).json()
    pages = requests.get(f"{GRAPH}/me/accounts", params={"access_token": long["access_token"], "fields": "id,name,access_token,instagram_business_account"}, timeout=30).json().get("data", [])
    if not pages: raise RuntimeError("No Facebook Pages found for this account")
    want = env("FB_PAGE_ID"); p = next((x for x in pages if x["id"] == want), pages[0])  # page tokens from long-lived user token don't expire
    save_token("meta", {"page_id": p["id"], "page_name": p["name"], "page_token": p["access_token"],
                        "ig_user_id": (p.get("instagram_business_account") or {}).get("id", "")})
    return p

def fb_params(title, caption, token):
    return {"title": title or "", "description": caption or "", "published": "true",
            "privacy": '{"value":"EVERYONE"}', "access_token": token}

def upload_facebook(path: Path, title: str, caption: str):
    t = _tok()
    if not (t["page_id"] and t["page_token"]): raise RuntimeError("Facebook not connected")
    with open(path, "rb") as f:
        r = requests.post(f"https://graph-video.facebook.com/{GRAPH.rsplit('/',1)[1]}/{t['page_id']}/videos",
                          data=fb_params(title, caption, t["page_token"]), files={"source": (path.name, f, "video/mp4")}, timeout=1800).json()
    if "id" not in r: raise RuntimeError(f"Facebook: {r}")
    return {"id": r["id"], "url": f"https://www.facebook.com/{r['id']}", "visibility": "public"}

def ig_container_params(video_url, caption, token):
    return {"media_type": "REELS", "video_url": video_url, "caption": caption or "", "share_to_feed": "true", "access_token": token}

def upload_instagram(path: Path, title: str, caption: str, public_url: str):
    t = _tok()
    if not (t["ig_user_id"] and t["page_token"]): raise RuntimeError("Instagram not connected (need IG Business/Creator linked to Page)")
    if not public_url.startswith("https://"): raise RuntimeError("Instagram needs a public https URL (set PUBLIC_BASE_URL, e.g. cloudflared tunnel)")
    r = requests.post(f"{GRAPH}/{t['ig_user_id']}/media", data=ig_container_params(public_url, caption, t["page_token"]), timeout=60).json()
    if "id" not in r: raise RuntimeError(f"Instagram container: {r}")
    cid = r["id"]
    for _ in range(120):
        s = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": t["page_token"]}, timeout=30).json()
        log.info("Instagram container %s", s.get("status_code"))
        if s.get("status_code") == "FINISHED": break
        if s.get("status_code") == "ERROR": raise RuntimeError(f"Instagram processing error: {s}")
        time.sleep(5)
    else: raise RuntimeError("Instagram processing timed out")
    p = requests.post(f"{GRAPH}/{t['ig_user_id']}/media_publish", data={"creation_id": cid, "access_token": t["page_token"]}, timeout=60).json()
    if "id" not in p: raise RuntimeError(f"Instagram publish: {p}")
    return {"id": p["id"], "visibility": "public"}  # IG Business/Creator posts are always public
