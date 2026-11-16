import time
from pathlib import Path
from unittest import mock
import pytest
from app import core, settings_store, config

@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "jobs.json"); core.JOBS.clear(); yield tmp_path; core.JOBS.clear()

def test_mask():
    assert settings_store.mask("abcdefgh1234") == "••••••••1234" and settings_store.mask("") == ""

def test_write_env_keeps_and_blank_unchanged(tmp_path):
    f = tmp_path / ".env"; f.write_text("# comment\nTIKTOK_CLIENT_KEY=old\nOTHER=x\n")
    settings_store.write_env({"TIKTOK_CLIENT_KEY": "new", "TIKTOK_CLIENT_SECRET": "", "FB_APP_ID": "123"}, f)
    txt = f.read_text()
    assert "TIKTOK_CLIENT_KEY=new" in txt and "OTHER=x" in txt and "# comment" in txt
    assert "FB_APP_ID=123" in txt and "TIKTOK_CLIENT_SECRET" not in txt
    assert config.env("FB_APP_ID") == "123"   # live, no restart

def test_save_writes_google_json(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "ENV_FILE", tmp_path / ".env"); monkeypatch.setattr(settings_store, "ROOT", tmp_path)
    monkeypatch.setattr(settings_store, "reload_env", lambda: None)
    ch = settings_store.save({"GOOGLE_CLIENT_ID": "id.apps", "GOOGLE_CLIENT_SECRET": "sec"}, "http://localhost:8000")
    assert "client_secret.json" in ch and '"client_id": "id.apps"' in (tmp_path / "client_secret.json").read_text()

def test_scheduler_fires_and_persists(tmpdb):
    v = tmpdb / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube", "tiktok"], run_at=time.time() + 3600)
    assert core.JOBS[jid]["state"] == "scheduled" and core.scheduler_tick(threaded=False) == []
    core.load_jobs(); assert core.JOBS[jid]["state"] == "scheduled"   # survives restart
    with mock.patch.object(core, "upload_one", return_value={"id": "X"}) as up:
        assert core.scheduler_tick(now=time.time() + 7200, threaded=False) == [jid]
    assert up.call_count == 2 and core.JOBS[jid]["state"] == "finished"
    assert core.JOBS[jid]["results"]["youtube"]["state"] == "done"
    core.load_jobs(); assert core.JOBS[jid]["results"]["tiktok"]["id"] == "X"   # history persisted

def test_cancel_reschedule(tmpdb):
    v = tmpdb / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube"], run_at=time.time() + 60)
    assert core.cancel(jid) and core.scheduler_tick(now=time.time() + 999, threaded=False) == []
    assert core.reschedule(jid, time.time() + 10) and core.JOBS[jid]["state"] == "scheduled"

def test_interrupted_marked(tmpdb):
    v = tmpdb / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube"], start=False); core.JOBS[jid]["state"] = "running"; core.save_jobs()
    core.load_jobs(); assert core.JOBS[jid]["results"]["youtube"]["state"] == "error"

def test_parse_local_and_watch_schedule(tmp_path):
    ts = core.parse_local("2030-01-02T03:04"); assert core.fmt_local(ts) == "2030-01-02 03:04"
    v = tmp_path / "a.mp4"; v.write_bytes(b"1"); v.with_suffix(".txt").write_text("T\nschedule: 2030-01-02 03:04\ncap")
    t, c, _, when = core._caption_for(v); assert (t, c, when) == ("T", "cap", ts)
