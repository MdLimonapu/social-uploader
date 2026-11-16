import sys
import uvicorn
from .config import env, ON_RENDER, log
from .main import app

if ON_RENDER and not env("APP_PASSWORD"):
    log.error("APP_PASSWORD must be set when the app is public (Render). Refusing to start."); sys.exit(1)
host = env("HOST") or env("APP_HOST", "0.0.0.0" if ON_RENDER else "127.0.0.1")
uvicorn.run(app, host=host, port=int(env("PORT") or env("APP_PORT", "8000")),
            proxy_headers=True, forwarded_allow_ips="*" if ON_RENDER else "127.0.0.1")
