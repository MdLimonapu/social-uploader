"""Optional password protection (APP_PASSWORD). Signed, stateless session cookie valid 30 days."""
import hashlib, hmac, secrets, time
from .config import ROOT, env

COOKIE = "su_session"
MAX_AGE = 30 * 86400
PUBLIC_PREFIXES = ("/static/", "/media/", "/login", "/logout", "/health")

def enabled(): return bool(env("APP_PASSWORD"))

def _secret():
    base = env("SESSION_SECRET")   # set on Render so logins survive restarts of the ephemeral disk
    if not base:
        p = ROOT / "tokens" / "session_secret"
        if not p.exists(): p.write_text(secrets.token_hex(32))
        base = p.read_text().strip()
    # mixing in the password means changing APP_PASSWORD logs everyone out
    return hashlib.sha256((base + "|" + env("APP_PASSWORD")).encode()).digest()

def make_cookie(now=None):
    exp = str(int((now or time.time()) + MAX_AGE))
    return exp + "." + hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()

def valid_cookie(val, now=None):
    try:
        exp, sig = (val or "").split(".", 1)
        return hmac.compare_digest(sig, hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()) and int(exp) > (now or time.time())
    except ValueError: return False

def check_password(pw): return enabled() and hmac.compare_digest((pw or "").encode(), env("APP_PASSWORD").encode())

def is_public(path):
    if path.startswith(PUBLIC_PREFIXES): return True
    parts = path.strip("/").split("/")
    return len(parts) == 3 and parts[0] == "oauth" and parts[2] == "callback"
