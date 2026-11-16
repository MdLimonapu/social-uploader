"""Mock tests: verify request building without real API keys."""
import json, os
from pathlib import Path
from unittest import mock
from app.platforms import youtube, tiktok, meta
from app import core

def test_youtube_body():
    b = youtube.build_body("T" * 150, "cap", "unlisted")
    assert len(b["snippet"]["title"]) == 100 and b["status"]["privacyStatus"] == "unlisted"

def test_tiktok_chunks():
    assert tiktok.chunk_plan(10_000_000) == (10_000_000, 1)
    cs, n = tiktok.chunk_plan(100 * 1024 * 1024); assert cs == 10 * 1024 * 1024 and n == 10
    os.environ.pop("TIKTOK_PRIVACY", None)
    b = tiktok.build_init(1234, "hi #tag")
    assert b["source_info"]["source"] == "FILE_UPLOAD" and b["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"

def test_tiktok_upload_flow(tmp_path):
    v = tmp_path / "v.mp4"; v.write_bytes(b"x" * 1000)
    post = mock.Mock(side_effect=[mock.Mock(json=lambda: {"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}}),
                                  mock.Mock(json=lambda: {"data": {"publish_id": "p1", "upload_url": "https://up"}, "error": {"code": "ok"}}),
                                  mock.Mock(json=lambda: {"data": {"status": "PUBLISH_COMPLETE"}})])
    put = mock.Mock(return_value=mock.Mock(status_code=201))
    with mock.patch.object(tiktok, "access_token", return_value="T"), mock.patch("requests.post", post), mock.patch("requests.put", put):
        r = tiktok.upload(v, "t", "c")
    assert r["status"] == "PUBLISH_COMPLETE"
    assert put.call_args.kwargs["headers"]["Content-Range"] == "bytes 0-999/1000"

def test_meta_params():
    assert meta.ig_container_params("https://x/v.mp4", "c", "T")["media_type"] == "REELS"
    assert meta.fb_params("t", "d", "T")["description"] == "d"

def test_ig_requires_https(tmp_path):
    with mock.patch.object(meta, "_tok", return_value={"page_id": "1", "page_token": "T", "ig_user_id": "9"}):
        try: meta.upload_instagram(tmp_path / "v.mp4", "", "", ""); assert False
        except RuntimeError as e: assert "https" in str(e)

def test_ig_flow(tmp_path):
    post = mock.Mock(side_effect=[mock.Mock(json=lambda: {"id": "c1"}), mock.Mock(json=lambda: {"id": "m1"})])
    get = mock.Mock(return_value=mock.Mock(json=lambda: {"status_code": "FINISHED"}))
    with mock.patch.object(meta, "_tok", return_value={"page_id": "1", "page_token": "T", "ig_user_id": "9"}), \
         mock.patch("requests.post", post), mock.patch("requests.get", get):
        assert meta.upload_instagram(tmp_path / "v.mp4", "", "c", "https://pub/v.mp4") == {"id": "m1", "visibility": "public"}
    assert post.call_args_list[0].kwargs["data"]["video_url"] == "https://pub/v.mp4"

def test_watch_caption(tmp_path):
    v = tmp_path / "a.mp4"; v.write_bytes(b"1"); v.with_suffix(".txt").write_text("My title\nline1\n#tag")
    t, c, txt, when = core._caption_for(v); assert t == "My title" and c == "line1\n#tag" and when is None
