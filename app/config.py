import os, json, logging
from pathlib import Path
from dotenv import load_dotenv

# In Docker, keep logins, jobs and uploaded files on a persistent volume rather
# than inside the image. Local installs retain the project directory by default.
ROOT = Path(os.getenv("SOCIAL_UPLOADER_DATA_DIR", Path(__file__).resolve().parent.parent)).resolve()
load_dotenv(ROOT / ".env")

# Render (and similar hosts): use the fixed public URL Render provides; no tunnel needed.
ON_RENDER = bool(os.getenv("RENDER_EXTERNAL_URL"))
if ON_RENDER:
    for _k in ("BASE_URL", "PUBLIC_BASE_URL"):
        if not os.getenv(_k, "").strip(): os.environ[_k] = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")

for d in ("inbox", "done", "uploads", "tokens", "logs", "failed", "data"):
    (ROOT / d).mkdir(parents=True, exist_ok=True)

def reload_env():
    """Re-read .env into the process (used after saving settings; no restart needed)."""
    load_dotenv(ROOT / ".env", override=True)

def env(k, default=""):
    v = os.getenv(k, default)
    return (v.split("#")[0].strip() if v else default)

BASE_URL = env("BASE_URL", "http://localhost:8000").rstrip("/")
GRAPH = f"https://graph.facebook.com/{env('GRAPH_VERSION','v21.0')}"
TOKENS = ROOT / "tokens"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger("uploader")

def _seed_files():
    """Ephemeral disks (Render free): recreate logins/secrets from env vars when the files are missing."""
    tok = ROOT / "tokens"
    seeds = {tok / "youtube.json": "YOUTUBE_TOKEN_JSON", tok / "instagram.json": "INSTAGRAM_TOKEN_JSON",
             ROOT / (env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json") or "client_secret.json"): "GOOGLE_CLIENT_SECRET_JSON"}
    for path, key in seeds.items():
        val = os.getenv(key, "").strip()
        if path.exists() or not val: continue
        try: json.loads(val)
        except ValueError: log.warning("%s is not valid JSON; ignored", key); continue
        path.write_text(val); log.info("Restored %s from %s", path.name, key)
    sec = ROOT / (env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json") or "client_secret.json")
    if not sec.exists() and env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET"):
        sec.write_text(json.dumps({"web": {"client_id": env("GOOGLE_CLIENT_ID"), "client_secret": env("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"{BASE_URL}/oauth/youtube/callback"]}}, indent=2))
        log.info("Created %s from GOOGLE_CLIENT_ID/SECRET", sec.name)

def load_token(name):
    p = TOKENS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None

def save_token(name, data):
    (TOKENS / f"{name}.json").write_text(json.dumps(data, indent=2))

_seed_files()
