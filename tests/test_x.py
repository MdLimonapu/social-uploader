"""X (Twitter) platform: OAuth 2.0 + PKCE, caption limits, chunked upload, jobs."""
import base64, hashlib, time, urllib.parse
from unittest import mock
import pytest
from app.platforms import x
from app import core, config


def R(d, code=200):
    return mock.Mock(status_code=code, json=lambda: d, text=str(d))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "client-id")
    monkeypatch.setenv("X_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    x._state.clear()


@pytest.fixture
def public_client(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "client-id")
    monkeypatch.delenv("X_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    x._state.clear()


def test_configured_requires_client_id_only(monkeypatch):
    monkeypatch.delenv("X_CLIENT_ID", raising=False)
    monkeypatch.delenv("X_CLIENT_SECRET", raising=False)
    assert not x.configured()
    monkeypatch.setenv("X_CLIENT_ID", "abc")
    assert x.configured()


def test_auth_url_pkce_and_scopes(env):
    url = x.auth_url()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith(x.AUTH)
    assert q["client_id"] == ["client-id"]
    assert q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://localhost:8000/oauth/x/callback"]
    assert q["scope"] == [x.SCOPES]
    assert q["code_challenge_method"] == ["S256"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(x._state["verifier"].encode("ascii")).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == [expected] and x._state["s"] == q["state"][0]


def test_auth_url_requires_client_id(monkeypatch):
    monkeypatch.delenv("X_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="X_CLIENT_ID"):
        x.auth_url()


def test_redirect_follows_base_url(env, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://social-uploader-r3j2.onrender.com/")
    assert x.redirect_uri() == "https://social-uploader-r3j2.onrender.com/oauth/x/callback"


def test_token_auth_confidential_uses_basic(env):
    headers, data = x._token_auth()
    assert data["client_id"] == "client-id"
    expected = base64.b64encode(b"client-id:client-secret").decode()
    assert headers["Authorization"] == f"Basic {expected}"


def test_token_auth_public_has_no_basic(public_client):
    headers, data = x._token_auth()
    assert "Authorization" not in headers and data["client_id"] == "client-id"


def test_callback_exchanges_code_and_stores_profile(env):
    x.auth_url(); st, ver = x._state["s"], x._state["verifier"]
    saved = {}
    def post(url, **kw):
        assert url == x.TOKEN
        assert kw["data"]["grant_type"] == "authorization_code"
        assert kw["data"]["code"] == "CODE" and kw["data"]["code_verifier"] == ver
        assert "Basic " in kw["headers"]["Authorization"]
        return R({"access_token": "AT", "refresh_token": "RT", "expires_in": 7200, "token_type": "bearer"})
    def get(url, **kw):
        assert url == x.ME
        return R({"data": {"id": "42", "username": "brocodes", "name": "Bro"}})
    with mock.patch.object(x, "load_token", return_value=None), \
         mock.patch.object(x, "save_token", lambda n, d: saved.update(d)), \
         mock.patch.object(x, "_request", side_effect=lambda method, url, **kw: post(url, **kw) if method == "POST" else get(url, **kw)):
        tok = x.callback("CODE", st)
    assert tok["access_token"] == "AT" and saved["username"] == "brocodes" and saved["user_id"] == "42"
    assert saved["refresh_token"] == "RT" and saved["expires_at"] < time.time() + 7200


def test_bad_state(env):
    x.auth_url()
    with pytest.raises(RuntimeError, match="state"):
        x.callback("c", "nope")


def test_access_token_refreshes(env):
    now = time.time()
    store = {"access_token": "OLD", "refresh_token": "RT", "expires_at": now - 10}
    def post(url, **kw):
        assert kw["data"]["grant_type"] == "refresh_token" and kw["data"]["refresh_token"] == "RT"
        return R({"access_token": "NEW", "refresh_token": "RT2", "expires_in": 7200})
    with mock.patch.object(x, "load_token", lambda n: store), \
         mock.patch.object(x, "save_token", lambda n, d: store.update(d)), \
         mock.patch.object(x, "_request", side_effect=lambda method, url, **kw: post(url, **kw)):
        assert x.access_token() == "NEW"
    assert store["refresh_token"] == "RT2"


def test_tweet_text_truncation():
    assert x.tweet_text("Title", "Caption here") == "Caption here"
    assert x.tweet_text("Only title", "") == "Only title"
    long = ("word " * 80).strip()
    out = x.tweet_text("", long)
    assert len(out) <= 280 and out.endswith("…") and " " not in out[-2:]
    hard = "A" * 400
    assert x.tweet_text("", hard) == "A" * 279 + "…"
    assert len(x.tweet_text("", "ok")) == 2


def test_media_type(tmp_path):
    assert x.media_type(tmp_path / "v.mp4") == "video/mp4"
    assert x.media_type(tmp_path / "v.MOV") == "video/quicktime"
    assert x.media_type(tmp_path / "v.webm") == "video/webm"


def test_upload_chunked_flow(tmp_path, monkeypatch, env):
    monkeypatch.setattr(x, "CHUNK", 8)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    v = tmp_path / "clip.mp4"; v.write_bytes(b"abcdefghij")  # 10 bytes → 2 chunks
    posts, gets = [], []

    def request(method, url, **kw):
        if method == "POST":
            posts.append((url, kw))
            if url == x.INIT:
                assert kw["json"] == {"media_type": "video/mp4", "total_bytes": 10, "media_category": "tweet_video"}
                return R({"data": {"id": "M1", "media_key": "13_M1"}})
            if url == x.APPEND.format(id="M1"):
                return R({"data": {"expires_after_secs": 86400}})
            if url == x.FINALIZE.format(id="M1"):
                return R({"data": {"id": "M1", "processing_info": {"state": "pending", "check_after_secs": 0}}})
            if url == x.TWEETS:
                assert kw["json"] == {"text": "hello world", "media": {"media_ids": ["M1"]}}
                return R({"data": {"id": "T9", "text": "hello world"}})
        if method == "GET":
            gets.append((url, kw))
            assert url == x.STATUS and kw["params"] == {"command": "STATUS", "media_id": "M1"}
            if len(gets) == 1:
                return R({"data": {"processing_info": {"state": "in_progress", "check_after_secs": 0}}})
            return R({"data": {"processing_info": {"state": "succeeded"}}})
        raise AssertionError((method, url))

    with mock.patch.object(x, "access_token", return_value="TOK"), mock.patch.object(x, "_request", side_effect=request):
        r = x.upload(v, "ignored title", "hello world")
    assert r == {"id": "T9", "media_id": "M1", "visibility": "public", "url": "https://x.com/i/web/status/T9"}
    appends = [kw for url, kw in posts if url.endswith("/append")]
    assert len(appends) == 2
    assert appends[0]["data"]["segment_index"] == 0 and appends[1]["data"]["segment_index"] == 1
    assert appends[0]["files"]["media"][1] == b"abcdefgh" and appends[1]["files"]["media"][1] == b"ij"
    assert len(gets) == 2


def test_request_retries_transient(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    seq = [R({}, 503), R({"ok": True}, 200)]
    with mock.patch("requests.request", side_effect=seq):
        r = x._request("POST", "https://api.x.com/2/media/upload/1/append")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_job_routes_and_scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "j.json"); core.JOBS.clear()
    v = tmp_path / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["x"], start=False)
    with mock.patch.object(x, "upload", return_value={"id": "T1"}) as up:
        core.run_job(jid)
    up.assert_called_once()
    assert up.call_args.args[1:] == ("t", "c")
    assert core.JOBS[jid]["results"]["x"]["state"] == "done"
    jid2 = core.create_job(v, "t", "c", ["x"], run_at=time.time() + 60)
    with mock.patch.object(x, "upload", return_value={"id": "T2"}):
        assert core.scheduler_tick(now=time.time() + 120, threaded=False) == [jid2]
    assert core.JOBS[jid2]["results"]["x"]["state"] == "done"
    core.JOBS.clear()


def test_status_and_upload_page(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("X_CLIENT_ID", raising=False)
    st = core.status()["x"]
    assert st["configured"] is False
    html = TestClient(main.app).get("/").text
    assert 'value="x"' in html and "Post to" in html
    settings = TestClient(main.app).get("/settings").text
    assert "X_CLIENT_ID is missing" in settings and "developer.x.com" in settings
    assert "/oauth/x/callback" in settings and 'name="X_CLIENT_ID"' in settings


def test_seed_x_token_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path); (tmp_path / "tokens").mkdir()
    monkeypatch.setenv("X_TOKEN_JSON", '{"access_token": "SEEDED"}')
    for k in ("YOUTUBE_TOKEN_JSON", "INSTAGRAM_TOKEN_JSON", "GOOGLE_CLIENT_SECRET_JSON",
              "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    config._seed_files()
    assert (tmp_path / "tokens" / "x.json").read_text() == '{"access_token": "SEEDED"}'
