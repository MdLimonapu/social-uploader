"""YouTube normal (long-form) video option: no Shorts checks, no #Shorts, tags, scheduler/watch support."""
import time
from unittest import mock
from app import core
from app.platforms import youtube, shorts


def test_body_normal_video_has_no_shorts_tag():
    b = youtube.build_body("My long vlog", "Full description\nline 2", "unlisted", shorts=False, tags="travel, #vlog, travel")
    assert b["snippet"]["title"] == "My long vlog"
    assert b["snippet"]["description"] == "Full description\nline 2"
    assert "#shorts" not in (b["snippet"]["title"] + b["snippet"]["description"]).lower()
    assert b["snippet"]["tags"] == ["travel", "vlog"]
    assert b["status"]["privacyStatus"] == "unlisted"


def test_body_shorts_unchanged():
    b = youtube.build_body("Trip", "desc")
    assert "#Shorts" in b["snippet"]["title"] and "tags" not in b["snippet"]


def test_title_and_description_limits():
    b = youtube.build_body("T" * 150, "d" * 6000, shorts=False)
    assert len(b["snippet"]["title"]) == 100 and len(b["snippet"]["description"]) == 5000


def test_parse_tags_limit():
    assert youtube.parse_tags(["a" * 300, "b" * 300]) == ["a" * 300]
    assert youtube.parse_tags("") == []


def _fake_yt(vid="V9"):
    yt = mock.MagicMock()
    yt.videos.return_value.insert.return_value.next_chunk.return_value = (None, {"id": vid, "status": {"privacyStatus": "public"}})
    yt.videos.return_value.list.return_value.execute.return_value = {"items": [{"status": {"privacyStatus": "public"}}]}
    return yt


def test_normal_upload_skips_shorts_check_and_streams_resumable(tmp_path):
    v = tmp_path / "long.mp4"; v.write_bytes(b"x")
    yt = _fake_yt()
    with mock.patch.object(shorts, "check_short", side_effect=AssertionError("must not be called")), \
         mock.patch.object(youtube, "credentials", return_value=object()), \
         mock.patch("googleapiclient.discovery.build", return_value=yt), \
         mock.patch("googleapiclient.http.MediaFileUpload") as mfu:
        r = youtube.upload(v, "Long", "desc", "public", shorts=False, tags=["a"])
    assert r["url"] == "https://www.youtube.com/watch?v=V9"
    assert mfu.call_args.kwargs["resumable"] is True and mfu.call_args.kwargs["chunksize"] == 8 * 1024 * 1024
    body = yt.videos.return_value.insert.call_args.kwargs["body"]
    assert body["snippet"]["title"] == "Long" and body["snippet"]["tags"] == ["a"]


def test_shorts_upload_still_checks(tmp_path):
    v = tmp_path / "s.mp4"; v.write_bytes(b"x")
    with mock.patch.object(shorts, "check_short", return_value=(False, "Not a Short: horizontal")):
        try: youtube.upload(v, "t", "c"); assert False
        except RuntimeError as e: assert "Not a Short" in str(e)


def test_next_chunk_retries_transient(monkeypatch):
    from googleapiclient.errors import HttpError
    monkeypatch.setattr(time, "sleep", lambda s: None)
    req = mock.MagicMock()
    err = HttpError(mock.MagicMock(status=503), b"busy")
    req.next_chunk.side_effect = [err, (None, {"id": "x"})]
    assert youtube._next_chunk(req) == (None, {"id": "x"})


def test_job_routes_youtube_video(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "j.json"); core.JOBS.clear()
    v = tmp_path / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube", "youtube_video"], start=False, yt_privacy="private", yt_tags="a, b")
    assert core.JOBS[jid]["yt_tags"] == ["a", "b"]
    with mock.patch.object(youtube, "upload", return_value={"id": "1"}) as up: core.run_job(jid)
    calls = up.call_args_list
    assert calls[0].args[3] == "private" and calls[0].kwargs == {}
    assert calls[1].kwargs == {"shorts": False, "tags": ["a", "b"]}
    assert core.JOBS[jid]["results"]["youtube_video"]["state"] == "done"; core.JOBS.clear()


def test_scheduler_fires_youtube_video(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "j.json"); core.JOBS.clear()
    v = tmp_path / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube_video"], run_at=time.time() + 60)
    with mock.patch.object(youtube, "upload", return_value={"id": "1"}):
        assert core.scheduler_tick(now=time.time() + 120, threaded=False) == [jid]
    assert core.JOBS[jid]["results"]["youtube_video"]["state"] == "done"; core.JOBS.clear()


def test_watch_txt_tags(tmp_path):
    v = tmp_path / "a.mp4"; v.write_bytes(b"x")
    (tmp_path / "a.txt").write_text("Title\ntags: x, y\nCaption here")
    title, cap, txt, run_at, tags = core._caption_and_tags(v)
    assert (title, cap, tags) == ("Title", "Caption here", ["x", "y"])


def test_upload_page_shows_option(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    html = TestClient(main.app).get("/").text
    assert 'value="youtube_video"' in html and "YouTube (normal video)" in html and 'name="yt_tags"' in html
