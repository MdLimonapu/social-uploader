import time
from unittest import mock
import pytest
from fastapi.testclient import TestClient
from app import auth, main, core

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_startup", lambda: None)
    main.app.router.on_startup.clear()
    return TestClient(main.app, follow_redirects=False)

def test_open_when_no_password(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert client.get("/settings").status_code == 200 and client.get("/api/status").status_code == 200

def test_locked_routes(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    r = client.get("/settings"); assert r.status_code == 303 and r.headers["location"] == "/login?next=/settings"
    assert client.get("/api/status").status_code == 401
    assert client.post("/settings").status_code == 401
    assert client.get("/login").status_code == 200 and "Welcome back" in client.get("/login").text

def test_public_exceptions(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    assert client.get("/media/nope/v.mp4").status_code == 404        # reached the route, not redirected
    assert client.get("/static/app.css").status_code == 200
    r = client.get("/oauth/tiktok/callback?error=denied"); assert r.status_code == 200 and "Connect failed" in r.text
    assert client.get("/oauth/tiktok/other").status_code == 303

def test_login_flow(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    with mock.patch("time.sleep"):
        bad = client.post("/login", data={"password": "nope", "next": "/jobs"})
    assert bad.status_code == 401 and "Wrong password" in bad.text
    ok = client.post("/login", data={"password": "s3cret", "next": "/jobs"})
    assert ok.status_code == 303 and ok.headers["location"] == "/jobs"
    ck = ok.headers["set-cookie"]; assert "Max-Age=2592000" in ck and "HttpOnly" in ck
    assert client.get("/jobs").status_code == 200
    client.get("/logout"); client.cookies.clear(); assert client.get("/jobs").status_code == 303

def test_open_redirect_blocked(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "p")
    r = client.post("/login", data={"password": "p", "next": "//evil.com"}); assert r.headers["location"] == "/"

def test_cookie_expiry_and_password_change(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "a")
    c = auth.make_cookie(); assert auth.valid_cookie(c)
    assert not auth.valid_cookie(c, now=time.time() + 31 * 86400)
    assert not auth.valid_cookie("123.bad") and not auth.valid_cookie("")
    monkeypatch.setenv("APP_PASSWORD", "b"); assert not auth.valid_cookie(c)

def test_delete_after_post(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "j.json"); core.JOBS.clear()
    up = core.ROOT / "uploads" / "test_delete_me.mp4"; up.write_bytes(b"x")
    jid = core.create_job(up, "t", "c", ["youtube"], start=False)
    with mock.patch.object(core, "upload_one", return_value={"id": "1"}): core.run_job(jid)
    assert not up.exists() and core.JOBS[jid]["deleted"]
    monkeypatch.setenv("DELETE_AFTER_POST", "false"); up.write_bytes(b"x")
    jid = core.create_job(up, "t", "c", ["youtube"], start=False)
    with mock.patch.object(core, "upload_one", return_value={"id": "1"}): core.run_job(jid)
    assert up.exists(); up.unlink(); core.JOBS.clear()
