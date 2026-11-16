import time, urllib.parse
from unittest import mock
import pytest
from app.platforms import instagram, meta
from app import core

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_ID", "123"); monkeypatch.setenv("INSTAGRAM_APP_SECRET", "sec"); monkeypatch.setenv("BASE_URL", "http://localhost:8000")

def R(d, code=200): return mock.Mock(status_code=code, json=lambda: d, text=str(d))

def test_auth_url(env):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(instagram.auth_url()).query)
    assert q["client_id"] == ["123"] and q["scope"] == ["instagram_business_basic,instagram_business_content_publish"]
    assert q["redirect_uri"] == ["http://localhost:8000/oauth/instagram/callback"]

def test_redirect_follows_base_url(env, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://abc.trycloudflare.com/")
    assert instagram.redirect_uri() == "https://abc.trycloudflare.com/oauth/instagram/callback"

def test_callback_exchanges_tokens(env):
    instagram.auth_url(); st = instagram._state["s"]; saved = {}
    post = mock.Mock(return_value=R({"access_token": "SHORT", "user_id": 1}))
    get = mock.Mock(side_effect=[R({"access_token": "LONG", "expires_in": 5184000}), R({"user_id": "1789", "username": "firestream_life"})])
    with mock.patch("requests.post", post), mock.patch("requests.get", get), mock.patch.object(instagram, "save_token", lambda n, d: saved.update(d)):
        instagram.callback("CODE#_", st)
    assert post.call_args.kwargs["data"]["code"] == "CODE" and post.call_args.args[0] == instagram.TOKEN
    assert get.call_args_list[0].kwargs["params"]["grant_type"] == "ig_exchange_token"
    assert saved["access_token"] == "LONG" and saved["user_id"] == "1789" and saved["username"] == "firestream_life"

def test_bad_state(env):
    with pytest.raises(RuntimeError): instagram.callback("c", "nope")

def test_refresh_when_near_expiry():
    now = time.time(); tok = {"access_token": "OLD", "expires_at": now + 86400, "issued_at": now - 50 * 86400, "user_id": "1"}; saved = {}
    with mock.patch.object(instagram, "load_token", return_value=dict(tok)), mock.patch.object(instagram, "save_token", lambda n, d: saved.update(d)), \
         mock.patch("requests.get", return_value=R({"access_token": "NEW", "expires_in": 5184000})) as g:
        assert instagram.access_token(now) == ("NEW", "1")
    assert g.call_args.kwargs["params"]["grant_type"] == "ig_refresh_token" and saved["access_token"] == "NEW"
    fresh = {"access_token": "A", "expires_at": now + 50 * 86400, "issued_at": now, "user_id": "1"}
    with mock.patch.object(instagram, "load_token", return_value=fresh), mock.patch("requests.get") as g2:
        assert instagram.access_token(now) == ("A", "1"); g2.assert_not_called()

def test_upload_flow(tmp_path):
    post = mock.Mock(side_effect=[R({"id": "C1"}), R({"id": "M1"})])
    get = mock.Mock(side_effect=[R({"status_code": "IN_PROGRESS"}), R({"status_code": "FINISHED"}), R({"permalink": "https://www.instagram.com/reel/x/"})])
    with mock.patch.object(instagram, "access_token", return_value=("T", "1789")), mock.patch("requests.post", post), mock.patch("requests.get", get):
        r = instagram.upload(tmp_path / "v.mp4", "t", "cap", "https://pub/v.mp4", poll=0)
    assert post.call_args_list[0].args[0] == "https://graph.instagram.com/v26.0/1789/media"
    d = post.call_args_list[0].kwargs["data"]; assert d["media_type"] == "REELS" and d["video_url"] == "https://pub/v.mp4" and d["caption"] == "cap"
    assert post.call_args_list[1].kwargs["data"]["creation_id"] == "C1"
    assert r == {"id": "M1", "visibility": "public", "url": "https://www.instagram.com/reel/x/"}

def test_upload_needs_https(tmp_path):
    with mock.patch.object(instagram, "access_token", return_value=("T", "1")):
        with pytest.raises(RuntimeError, match="https"): instagram.upload(tmp_path / "v.mp4", "", "", "")

def test_routing_prefers_instagram_login(tmp_path):
    v = tmp_path / "v.mp4"
    with mock.patch.object(instagram, "connected", return_value=True), mock.patch.object(meta, "ig_connected", return_value=True), \
         mock.patch.object(instagram, "upload", return_value={"id": "a"}) as a, mock.patch.object(meta, "upload_instagram") as b:
        core.upload_one("instagram", v, "t", "c", "https://x"); a.assert_called_once(); b.assert_not_called()
    with mock.patch.object(instagram, "connected", return_value=False), mock.patch.object(meta, "ig_connected", return_value=True), \
         mock.patch.object(meta, "upload_instagram", return_value={"id": "b"}) as b:
        core.upload_one("instagram", v, "t", "c", "https://x"); b.assert_called_once()

# ---- manual (pasted) token ----
@pytest.fixture
def manual(monkeypatch, tmp_path):
    for k in ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"): monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "IGAAmanual"); monkeypatch.setenv("INSTAGRAM_USER_ID", "17841430454727214")
    store = {}
    monkeypatch.setattr(instagram, "load_token", lambda n: store.get(n)); monkeypatch.setattr(instagram, "save_token", lambda n, d: store.__setitem__(n, dict(d)))
    return store

def test_manual_counts_as_connected(manual):
    assert instagram.connected() and instagram.configured()

def test_seed_manual_validates_and_refreshes(manual):
    get = mock.Mock(side_effect=[R({"user_id": "17841430454727214", "username": "firestream_life"}), R({"access_token": "FRESH", "expires_in": 5184000})])
    with mock.patch("requests.get", get): t = instagram.seed_manual()
    assert get.call_args_list[0].args[0] == "https://graph.instagram.com/v26.0/me"
    assert get.call_args_list[0].kwargs["params"]["fields"] == "user_id,username"
    assert get.call_args_list[1].args[0] == "https://graph.instagram.com/refresh_access_token"
    assert t["username"] == "firestream_life" and manual["instagram"]["access_token"] == "FRESH" and t["expires_at"]

def test_seed_manual_bad_token(manual):
    with mock.patch("requests.get", return_value=R({"error": {"message": "Invalid OAuth access token"}}, 400)):
        with pytest.raises(RuntimeError, match="token check"): instagram.seed_manual()

def test_manual_refresh_failure_keeps_token(manual):
    with mock.patch("requests.get", return_value=R({"error": "too new"}, 400)):
        assert instagram.access_token() == ("IGAAmanual", "17841430454727214")
    assert manual["instagram"]["next_refresh"] > time.time()

def test_manual_upload_posts_like_n8n(manual, tmp_path):
    manual["instagram"] = {"access_token": "IGAAmanual", "user_id": "17841430454727214", "source": "manual", "orig": "IGAAmanual",
                           "issued_at": time.time(), "expires_at": time.time() + 50 * 86400}
    post = mock.Mock(side_effect=[R({"id": "C"}), R({"id": "M"})])
    get = mock.Mock(side_effect=[R({"status_code": "FINISHED"}), R({})])
    with mock.patch("requests.post", post), mock.patch("requests.get", get):
        instagram.upload(tmp_path / "v.mp4", "", "cap", "https://pub/v.mp4", poll=0)
    assert post.call_args_list[0].args[0] == "https://graph.instagram.com/v26.0/17841430454727214/media"
    d = post.call_args_list[0].kwargs["data"]
    assert d == {"media_type": "REELS", "video_url": "https://pub/v.mp4", "caption": "cap", "share_to_feed": "true", "access_token": "IGAAmanual"}

def test_changed_env_token_is_adopted(manual, monkeypatch):
    manual["instagram"] = {"access_token": "OLD", "user_id": "1", "source": "manual", "orig": "OLDORIG", "issued_at": time.time(), "expires_at": time.time() + 50 * 86400}
    with mock.patch("requests.get", return_value=R({"error": "x"}, 400)):
        assert instagram.access_token() == ("IGAAmanual", "17841430454727214")
