import json
from unittest import mock
from pathlib import Path
from app.platforms import youtube, tiktok, meta, shorts
from app import core

def test_youtube_defaults_public(monkeypatch):
    monkeypatch.delenv("YOUTUBE_PRIVACY", raising=False)
    st = youtube.build_body("t", "c")["status"]
    assert st == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert youtube.build_body("t", "c", "unlisted")["status"]["privacyStatus"] == "unlisted"
    assert youtube.build_body("t", "c", "bogus")["status"]["privacyStatus"] == "public"

def test_forced_private_detection():
    assert "audit" in youtube.check_forced_private("public", "private")
    assert youtube.check_forced_private("public", "public") is None
    assert youtube.check_forced_private("private", "private") is None

def test_youtube_upload_warns_when_forced_private(tmp_path):
    yt = mock.MagicMock()
    req = yt.videos.return_value.insert.return_value; req.next_chunk.return_value = (None, {"id": "V1", "status": {"privacyStatus": "public"}})
    yt.videos.return_value.list.return_value.execute.return_value = {"items": [{"status": {"privacyStatus": "private"}}]}
    with mock.patch.object(shorts, "check_short", return_value=(True, "ok")), mock.patch.object(youtube, "credentials", return_value=object()), \
         mock.patch("googleapiclient.discovery.build", return_value=yt), mock.patch("googleapiclient.http.MediaFileUpload"):
        r = youtube.upload(tmp_path / "v.mp4", "t", "c", "public")
    assert r["visibility"] == "private" and "verification" in r["warning"]
    assert yt.videos.return_value.insert.call_args.kwargs["body"]["status"]["privacyStatus"] == "public"

def test_tiktok_pick_privacy(monkeypatch):
    monkeypatch.delenv("TIKTOK_PRIVACY", raising=False)
    assert tiktok.pick_privacy(["SELF_ONLY", "PUBLIC_TO_EVERYONE"]) == ("PUBLIC_TO_EVERYONE", None)
    p, w = tiktok.pick_privacy(["SELF_ONLY"]); assert p == "SELF_ONLY" and "audit" in w
    p, w = tiktok.pick_privacy(["FOLLOWER_OF_CREATOR", "SELF_ONLY"]); assert p == "FOLLOWER_OF_CREATOR" and w
    assert tiktok.pick_privacy([]) == ("PUBLIC_TO_EVERYONE", None)

def test_tiktok_upload_uses_creator_info(tmp_path):
    v = tmp_path / "v.mp4"; v.write_bytes(b"x" * 10)
    posts = [mock.Mock(json=lambda: {"data": {"privacy_level_options": ["SELF_ONLY"]}}),
             mock.Mock(json=lambda: {"data": {"publish_id": "p", "upload_url": "https://u"}, "error": {"code": "ok"}}),
             mock.Mock(json=lambda: {"data": {"status": "PUBLISH_COMPLETE"}})]
    post = mock.Mock(side_effect=posts)
    with mock.patch.object(tiktok, "access_token", return_value="T"), mock.patch("requests.post", post), \
         mock.patch("requests.put", return_value=mock.Mock(status_code=201)):
        r = tiktok.upload(v, "t", "c")
    assert post.call_args_list[1].kwargs["json"]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert r["visibility"] == "SELF_ONLY" and "warning" in r

def test_facebook_public():
    p = meta.fb_params("t", "d", "T"); assert p["published"] == "true" and json.loads(p["privacy"])["value"] == "EVERYONE"

def test_job_passes_yt_privacy(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB", tmp_path / "j.json"); core.JOBS.clear()
    v = tmp_path / "v.mp4"; v.write_bytes(b"x")
    jid = core.create_job(v, "t", "c", ["youtube"], start=False, yt_privacy="unlisted")
    with mock.patch.object(youtube, "upload", return_value={"id": "1"}) as up: core.run_job(jid)
    assert up.call_args.args[3] == "unlisted"; core.JOBS.clear()
