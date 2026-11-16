"""HTML layout + small components (no template engine, no build step)."""
import html, json

E = html.escape

ICONS = {
  "upload": '<path d="M12 16V4m0 0l-5 5m5-5l5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/>',
  "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>',
  "list": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
  "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
  "logs": '<path d="M4 4h16v16H4z"/><path d="M8 9l3 3-3 3M13 15h4"/>',
  "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  "moon": '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
  "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1"/>',
  "chevron": '<path d="M6 9l6 6 6-6"/>',
  "film": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  "x": '<path d="M6 6l12 12M18 6L6 18"/>',
  "link": '<path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1"/>',
  "folder": '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
  "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
}
def icon(name, size=18):
    return f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'

BRAND = {
  "youtube": ("YouTube Shorts", "#ff0033", '<svg viewBox="0 0 24 24" width="{s}" height="{s}"><rect x="1.5" y="4.5" width="21" height="15" rx="4.5" fill="#ff0033"/><path d="M10 8.8v6.4l5.6-3.2z" fill="#fff"/></svg>'),
  "youtube_video": ("YouTube (normal video)", "#ff0033", '<svg viewBox="0 0 24 24" width="{s}" height="{s}"><rect x="1.5" y="4.5" width="21" height="15" rx="4.5" fill="#ff0033"/><path d="M10 8.8v6.4l5.6-3.2z" fill="#fff"/><rect x="5" y="16.6" width="14" height="1.3" rx=".65" fill="#fff" opacity=".85"/></svg>'),
  "tiktok": ("TikTok", "#25f4ee", '<svg viewBox="0 0 24 24" width="{s}" height="{s}"><rect width="24" height="24" rx="6" fill="#111"/><path d="M14.2 5v9.1a2.9 2.9 0 11-2.4-2.9" fill="none" stroke="#25f4ee" stroke-width="2.2" transform="translate(-.6 .4)"/><path d="M14.2 5v9.1a2.9 2.9 0 11-2.4-2.9" fill="none" stroke="#fe2c55" stroke-width="2.2" transform="translate(.6 -.4)"/><path d="M14.2 5v9.1a2.9 2.9 0 11-2.4-2.9M14.2 5c.3 1.8 1.6 3 3.6 3.1" fill="none" stroke="#fff" stroke-width="2.2"/></svg>'),
  "instagram": ("Instagram", "#e1306c", '<svg viewBox="0 0 24 24" width="{s}" height="{s}"><defs><linearGradient id="igg" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#feda75"/><stop offset=".35" stop-color="#fa7e1e"/><stop offset=".6" stop-color="#d62976"/><stop offset="1" stop-color="#4f5bd5"/></linearGradient></defs><rect width="24" height="24" rx="6.5" fill="url(#igg)"/><rect x="5.5" y="5.5" width="13" height="13" rx="4" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="3.1" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="16.3" cy="7.7" r="1" fill="#fff"/></svg>'),
  "facebook": ("Facebook", "#1877f2", '<svg viewBox="0 0 24 24" width="{s}" height="{s}"><circle cx="12" cy="12" r="12" fill="#1877f2"/><path d="M13.3 24v-8.4h2.8l.4-3.3h-3.2v-2c0-.9.3-1.6 1.6-1.6h1.7V5.8a23 23 0 00-2.5-.1c-2.5 0-4.2 1.5-4.2 4.3v2.4H7.1v3.3h2.8V24z" fill="#fff"/></svg>'),
}
def brand(p, size=22): return BRAND[p][2].replace("{s}", str(size))
def pname(p): return BRAND[p][0]

def status_badge(s):
    if s["connected"]: return '<span class="badge ok"><i></i>Connected</span>'
    if not s["configured"]: return '<span class="badge bad"><i></i>Missing keys</span>'
    return '<span class="badge warn"><i></i>Not connected</span>'

STATE_BADGE = {"done": "ok", "finished": "ok", "error": "bad", "running": "info", "queued": "muted",
               "scheduled": "info", "cancelled": "muted"}
def state_badge(s, label=None):
    return f'<span class="badge {STATE_BADGE.get(s, "muted")}"><i></i>{E(label or s.title())}</span>'

NAV = [("/", "upload", "Upload"), ("/scheduled", "calendar", "Scheduled"), ("/jobs", "list", "Jobs"),
       ("/settings", "settings", "Settings"), ("/logs", "logs", "Logs")]

def layout(title, body, active="/", subtitle="", refresh=False, toasts=None, actions=""):
    nav = "".join(f'<a href="{h}" class="{"active" if h == active else ""}">{icon(i)}<span>{l}</span></a>' for h, i, l in NAV)
    t = E(json.dumps(toasts or []), quote=True)
    return f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(title)} · Social Uploader</title>
<script>try{{var q=new URLSearchParams(location.search).get('theme');if(q)localStorage.setItem('theme',q);document.documentElement.dataset.theme=q||localStorage.getItem('theme')||'dark'}}catch(e){{}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="/static/app.css"></head>
<body data-refresh="{1 if refresh else 0}" data-toasts="{t}">
<aside class="side"><div class="logo"><div class="logo-mark">{icon("bolt", 18)}</div><div><b>Social</b> Uploader</div></div>
<nav>{nav}</nav>
<button class="theme-btn" id="themeBtn" type="button" title="Toggle theme">{icon("sun")}{icon("moon")}<span>Theme</span></button></aside>
<main><header class="top"><div><h1>{title}</h1>{f'<p class="sub">{subtitle}</p>' if subtitle else ''}</div><div class="actions">{actions}</div></header>
{body}</main><div id="toasts"></div><script src="/static/app.js"></script></body></html>"""
