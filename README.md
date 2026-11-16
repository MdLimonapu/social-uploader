# Social Uploader (free, self-hosted, runs on your PC)

Drop in a video + caption → it posts to **YouTube, TikTok, Instagram (Reels) and Facebook (Page)** using the official APIs only. No paid services.

## 1. Start the app
1. Install **Python 3.10+** (python.org – on Windows tick "Add Python to PATH").
2. Unzip this folder. Windows: double-click **run.bat**. Mac/Linux: `./run.sh`
   (first run creates `.venv`, installs packages and copies `.env.example` → `.env`).
3. Open **http://localhost:8000**. The **Settings** page shows what's connected.

After editing `.env`, stop the app (Ctrl+C) and start it again.

## 2. One-click setup in Settings
Open **Settings**, paste your keys into the form and click **Save**. They're written to `.env` and used immediately, so you don't need to restart. Secrets show only their last 4 characters, and a field you leave blank keeps its old value. For YouTube, either paste the Google client ID and secret (the app creates `client_secret.json` for you) or upload the downloaded `client_secret.json`. After saving, follow the hint, e.g. *"Saved – now click Connect"*.

## 2b. Scheduling
On the Upload page choose **Schedule** and pick a date and time (your Mac's local time). The **Scheduled** page lists upcoming posts and lets you **Cancel** or **Reschedule** them. Scheduled posts and job history are stored in `data/jobs.json`, so they survive restarts. The app must be running at the scheduled time; if it was off, the post goes out as soon as you start the app. Watch folder: add a line `schedule: 2026-10-25 18:30` anywhere in the `.txt`.

## 2c. How to use
- **Upload page**: choose video, title, caption, tick platforms → Upload. You'll see a live status per platform.
- **YouTube Shorts vs. YouTube (normal video)**: both use the same YouTube connection. *Shorts* checks the video is vertical and ≤ 3 min and adds `#Shorts`. *Normal video* skips those checks, never adds `#Shorts`, keeps your full title (max 100 chars) and caption as the description (max 5,000), and uses the optional **YouTube tags** field. Both use the YouTube visibility setting and upload in resumable 8 MB chunks streamed from disk, so long/large videos don't need much RAM.
- **Watch folder**: put `myvideo.mp4` into `inbox/`. Optional `myvideo.txt` next to it: *line 1 = title, rest = caption/hashtags*. Optional lines `tags: a, b` (YouTube tags) and `schedule: …`. It posts to `WATCH_PLATFORMS` (`youtube` = Shorts, `youtube_video` = normal video) and then moves to `done/` (or `failed/` if every platform failed — check **Logs**).
- **Jobs** page = history (kept until restart). **Logs** page = `logs/app.log`.
- Disconnect a platform: delete its file in `tokens/`.

## 3. Get your free keys

### YouTube (Google Cloud – free)
1. https://console.cloud.google.com → create a project.
2. *APIs & Services → Library* → enable **YouTube Data API v3**.
3. *OAuth consent screen* → External → fill app name/email → add scope `youtube.upload` → add **your Google account as Test user**.
4. *Credentials → Create credentials → OAuth client ID* → type **Web application** → Authorized redirect URI: `http://localhost:8000/oauth/youtube/callback`.
5. Download JSON, rename to **client_secret.json**, put it in this folder.
6. Settings → YouTube → **Connect**.
- Limits: free quota ≈ 10,000 units/day; one upload costs ~1,600 → ~6 uploads/day. Videos from **unverified** apps (not passed Google's audit) are forced to **private** — you can make them public by hand in YouTube Studio. Test-mode refresh tokens expire after 7 days → just click Connect again.

### TikTok (developers.tiktok.com – free)
1. Sign up at https://developers.tiktok.com → *Manage apps → Connect an app*.
2. Add products **Login Kit** and **Content Posting API** (enable **Direct Post**).
3. Scopes: `user.info.basic`, `video.publish`.
4. Redirect URI: `http://localhost:8000/oauth/tiktok/callback` (if TikTok refuses localhost, see Troubleshooting).
5. In *Sandbox*, add your TikTok account as a target user. Copy **Client key / Client secret** into `.env` (`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`).
6. Settings → TikTok → **Connect**.
- **Limitation:** until TikTok audits your app, every post is **private (SELF_ONLY)** — only you can see it; change visibility in the TikTok app. Keep `TIKTOK_PRIVACY=SELF_ONLY`. Also limited daily posts per user.

### Instagram – Instagram Login (recommended, NO Facebook Page needed)
You need an Instagram **professional** account (Business or Creator). In the Instagram app: Settings → Account type and tools → Switch to professional account.

1. https://developers.facebook.com → log in → **My Apps → Create app**.
2. Enter an app name and your email. For the use case, choose **"Manage messaging & content on Instagram"** (older wording: Other → **Business** app type). Skip connecting a business portfolio if asked, then create the app.
3. In the left menu open **Instagram → API setup with Instagram login** (it may be under *Use cases → Customize*).
4. At the top of that page, copy the **Instagram app ID** and **Instagram app secret**. These are not the Facebook App ID and secret shown under App settings → Basic.
5. **Section "Set up Instagram business login" → Business login settings → OAuth redirect URIs**: add
   `http://localhost:8000/oauth/instagram/callback` and Save.
   If Meta says it must be **https**, see *"https redirect via tunnel"* below.
6. **Add your account as a tester** (the app is in Development mode): *App roles → Roles → Add people → **Instagram Tester*** → enter `firestream_life`.
   Then accept the invite. On instagram.com go to Settings → **Apps and websites → Tester invites → Accept**; on the phone it's Settings → Website permissions → Apps and websites.
7. Permissions are `instagram_business_basic` and `instagram_business_content_publish`. For your own tester account, the standard access level in Development mode is enough. App Review is only needed for other people's accounts.
8. In the app: **Settings → Instagram Reels card** → paste Instagram app ID and secret → **Save** → **Connect** → log in as @firestream_life → Allow.
   The card turns **Connected**. The token lasts 60 days and is refreshed automatically when it gets close to expiring, as long as the app is used at least once in that time.
9. Instagram also needs a **public video URL**; see the next section.

**https redirect via tunnel** (only if Meta rejects `http://localhost`):
- Start a tunnel: `cloudflared tunnel --url http://localhost:8000`, or better, an **ngrok free static domain** (`ngrok http --url=your-name.ngrok-free.app 8000`). The static domain never changes, so you register it only once.
- In Settings, set **BASE_URL** and **PUBLIC_BASE_URL** to the https address, e.g. `https://your-name.ngrok-free.app`.
- Register `https://your-name.ngrok-free.app/oauth/instagram/callback` as the redirect URI in Meta.
- Restart the app (the YouTube, TikTok and Facebook redirect addresses are read at start-up). Open the app **via the https address** and click Connect.
- A cloudflared quick tunnel gets a new address every time it starts. You would have to update the redirect URI each time, but only for connecting (once per ~60 days). Posting just needs PUBLIC_BASE_URL to be current.

### Facebook Page + Instagram (fallback, developers.facebook.com – free)
Only needed for posting to a **Facebook Page**, or if you prefer the older Page-linked Instagram route. If Instagram Login is connected, it is always used for Instagram.
Needs: a **Facebook Page**, and for Instagram an **Instagram Business or Creator account linked to that Page** (Instagram app → Settings → Account type; then link in Page settings → Linked accounts).
1. https://developers.facebook.com → *My Apps → Create app* → type **Business**.
2. Add products **Facebook Login for Business** (or Facebook Login) and **Instagram Graph API**.
3. Facebook Login → Settings → Valid OAuth Redirect URI: `http://localhost:8000/oauth/meta/callback` (localhost is allowed in development mode).
4. *App settings → Basic*: copy **App ID / App Secret** into `.env` (`FB_APP_ID`, `FB_APP_SECRET`). Optionally set `FB_PAGE_ID` if you manage several Pages.
5. Settings → Facebook → **Connect**, approve all Page/Instagram permissions. The app saves a non-expiring Page token and your IG account id.
- Alternative: create a Page token in *Graph API Explorer* and paste it into `FB_PAGE_ACCESS_TOKEN` + `FB_PAGE_ID` + `IG_USER_ID`.
- App stays in **Development mode** — fine since you're the admin posting to your own Page/IG.

### Instagram needs a public URL (important!)
Instagram's API cannot receive a file from your PC; it **downloads the video from a public https link**. Free option – Cloudflare quick tunnel:
1. Install `cloudflared` (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
2. While the app runs: `cloudflared tunnel --url http://localhost:8000`
3. Copy the `https://xxxx.trycloudflare.com` address into `.env` as `PUBLIC_BASE_URL`, restart the app.
The app only exposes the video being posted, under a random secret link, and removes it after posting. (`ngrok http 8000` works too.) The URL changes each time you start the tunnel. Alternatively paste a public https URL of the same video into the form's optional field.
- Reels: 3 s–15 min (90 s if you want Reels tab), MP4/H.264, 9:16 recommended; ~50 API posts per 24 h.

## 4. Troubleshooting
- **redirect_uri mismatch**: the URI in the console must match exactly (`http://localhost:8000/...`, no trailing slash). If you change port, update `BASE_URL`.
- **TikTok won't accept localhost redirect**: run a cloudflared tunnel, set `BASE_URL` to the tunnel URL, register `https://<tunnel>/oauth/tiktok/callback`, connect, then switch `BASE_URL` back.
- **Errors** are shown per platform on the job page and in Logs.
- Run tests: `.venv/bin/python -m pytest tests` (Windows: `.venv\Scripts\python -m pytest tests`, after `pip install pytest`).

## Files
`app/main.py` web UI & routes · `app/core.py` jobs + watch folder · `app/platforms/` youtube.py, tiktok.py, meta.py · `tokens/` saved logins (keep private!) · `.env` your keys (keep private!).

## 5. Always-on on a Linux VM (Google Cloud) with cloudflared

1. Install cloudflared: `curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cf.deb && sudo dpkg -i cf.deb`
2. In `.env` set **`APP_PASSWORD=`** to a strong password (the tunnel URL is public!). Optional: `HOST`/`PORT` (default 127.0.0.1:8000), `DELETE_AFTER_POST=true` (deletes the copy in `uploads/` after posting; watch-folder files still go to `done/`).
3. Test: `./start-always.sh` – it starts the tunnel, writes the `https://…trycloudflare.com` URL into `PUBLIC_BASE_URL` and `BASE_URL`, then runs the app. Settings → *Public URL* shows it.
4. Run forever: edit `User`/`WorkingDirectory`/`ExecStart` in `social-uploader.service`, then
   `sudo cp social-uploader.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now social-uploader`
   Logs: `journalctl -u social-uploader -f`.

Note: quick-tunnel URLs change on every restart, so OAuth redirect URIs registered with Google/TikTok/Meta must be updated (or use a named Cloudflare tunnel with your own domain for a fixed URL). Login lasts 30 days per device; changing APP_PASSWORD signs everyone out.

## 6. Free hosting on Render (fixed https URL, no tunnel)

The app runs on Render's **free** web service using the `Dockerfile`. When Render's `RENDER_EXTERNAL_URL` is present, the app:
- listens on `0.0.0.0:$PORT` and trusts Render's proxy headers;
- uses `RENDER_EXTERNAL_URL` as `BASE_URL` and `PUBLIC_BASE_URL` (unless you set them), so OAuth redirects and Instagram's video links use the fixed `https://<name>.onrender.com` address;
- refuses to start without `APP_PASSWORD` (the URL is public);
- exposes `GET /healthz` (no login) for Render's health check.

**Environment variables to set in Render** (never commit them): `APP_PASSWORD`, `SESSION_SECRET` (any long random string, keeps you signed in across restarts), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `YOUTUBE_PRIVACY`, `GRAPH_VERSION`, optional TikTok/Facebook keys.
Because the free disk is wiped on every restart, logins can be restored at start-up from these optional variables (paste the whole JSON file content):
`YOUTUBE_TOKEN_JSON` → `tokens/youtube.json`, `INSTAGRAM_TOKEN_JSON` → `tokens/instagram.json`, `GOOGLE_CLIENT_SECRET_JSON` → `client_secret.json` (otherwise it is built from `GOOGLE_CLIENT_ID`/`SECRET`).

Register these redirect URIs with the platforms: `https://<name>.onrender.com/oauth/youtube/callback` (Google Cloud → Credentials → your Web client), `https://<name>.onrender.com/oauth/instagram/callback` (Meta app → Instagram → Business login settings), and the `/oauth/tiktok/callback` / `/oauth/meta/callback` ones if you use them.

**Free plan limits:** the service sleeps after ~15 minutes without visits (the first visit takes ~1 minute to wake it), so scheduled posts only go out while it is awake. Files, uploads, job history and anything saved on the Settings page are lost on every restart or redeploy. Put permanent settings in Render's environment variables instead. After clicking **Connect** again, copy the new `tokens/*.json` into the matching `*_TOKEN_JSON` variable if you want it to survive restarts.
