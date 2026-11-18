"""Read/write credentials in .env, with masking. Blank submitted values keep the old value."""
import json, os, re
from .config import ROOT, env, reload_env

ENV_FILE = ROOT / ".env"
# (key, label, secret?, platform)
FIELDS = [
    ("GOOGLE_CLIENT_ID", "Google OAuth client ID", False, "youtube"),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth client secret", True, "youtube"),
    ("YOUTUBE_PRIVACY", "Default YouTube visibility", False, "youtube"),
    ("TIKTOK_CLIENT_KEY", "TikTok client key", False, "tiktok"),
    ("TIKTOK_CLIENT_SECRET", "TikTok client secret", True, "tiktok"),
    ("FB_APP_ID", "Meta app ID", False, "meta"),
    ("FB_APP_SECRET", "Meta app secret", True, "meta"),
    ("FB_PAGE_ID", "Facebook Page ID (optional)", False, "meta"),
    ("FB_PAGE_ACCESS_TOKEN", "Facebook Page access token (optional)", True, "meta"),
    ("IG_USER_ID", "Instagram user ID (optional)", False, "meta"),
    ("INSTAGRAM_APP_ID", "Instagram app ID (Instagram login)", False, "instagram"),
    ("INSTAGRAM_APP_SECRET", "Instagram app secret", True, "instagram"),
    ("INSTAGRAM_ACCESS_TOKEN", "…or paste a long-lived Instagram access token (e.g. from n8n)", True, "instagram"),
    ("INSTAGRAM_USER_ID", "Instagram user ID (with pasted token)", False, "instagram"),
    ("BASE_URL", "App base URL (https tunnel if Meta rejects localhost)", False, "instagram"),
    ("PUBLIC_BASE_URL", "Public base URL for Instagram (https://…trycloudflare.com)", False, "instagram"),
    ("X_CLIENT_ID", "X Client ID", False, "x"),
    ("X_CLIENT_SECRET", "X Client Secret (optional for public clients)", True, "x"),
    ("WATCH_PLATFORMS", "Watch-folder platforms (comma separated)", False, "watch"),
]
KEYS = {f[0] for f in FIELDS}
SECRET = {f[0] for f in FIELDS if f[2]}

def mask(v: str) -> str:
    if not v: return ""
    return "•" * 8 + v[-4:] if len(v) > 4 else "•" * len(v)

def current():
    return {k: env(k) for k in KEYS}

def write_env(updates: dict, path=None):
    """Update/add keys in .env, keeping other lines and comments. Blank values are ignored."""
    path = path or ENV_FILE
    if not path.exists():
        ex = ROOT / ".env.example"
        path.write_text(ex.read_text() if ex.exists() else "")
    updates = {k: v.strip() for k, v in updates.items() if v is not None and v.strip() != ""}
    changed = sorted(k for k, v in updates.items() if os.getenv(k, "") != v)
    if any("\n" in v for v in updates.values()): raise ValueError("values cannot contain newlines")
    lines, done = path.read_text().splitlines(), set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"; done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n")
    for k, v in updates.items(): os.environ[k] = v
    return changed

def write_google_secret(client_id, client_secret, base_url):
    data = {"web": {"client_id": client_id, "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [f"{base_url}/oauth/youtube/callback"]}}
    target = ROOT / (env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json") or "client_secret.json")
    target.write_text(json.dumps(data, indent=2))
    return target

def save(form: dict, base_url: str, uploaded_json: bytes | None = None):
    changed = write_env({k: form.get(k, "") for k in KEYS})
    if uploaded_json:
        j = json.loads(uploaded_json)
        if not ("web" in j or "installed" in j): raise ValueError("not a Google client_secret.json")
        (ROOT / (env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json") or "client_secret.json")).write_bytes(uploaded_json)
        changed.append("client_secret.json")
    elif env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET") and ({"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"} & set(changed)):
        write_google_secret(env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"), base_url); changed.append("client_secret.json")
    reload_env()
    return changed
