import subprocess, shutil
from unittest import mock
import pytest
from app.platforms import shorts, youtube

def test_title_tag():
    assert shorts.tag_title("Hello") == "Hello #Shorts"
    assert shorts.tag_title("Hi #shorts fun") == "Hi #shorts fun"           # no duplicate
    assert shorts.tag_title("x" * 95) == "x" * 95                           # doesn't fit -> untouched
    assert shorts.tag_title("x" * 92) == "x" * 92 + " #Shorts"              # exactly 100
    assert shorts.tag_title("") == "Untitled #Shorts"

def test_description_tag():
    assert shorts.tag_description("") == "#Shorts"
    assert shorts.tag_description("cool #travel") == "cool #travel\n\n#Shorts"
    assert shorts.tag_description("#Shorts first") == "#Shorts first"
    assert shorts.tag_description("x #ShortsFan").endswith("#Shorts") and "#ShortsFan\n" in shorts.tag_description("x #ShortsFan")

def test_build_body_has_tags():
    b = youtube.build_body("Trip", "desc")
    assert b["snippet"]["title"] == "Trip #Shorts" and b["snippet"]["description"].endswith("#Shorts")

@pytest.mark.parametrize("w,h,d,ok", [(1080, 1920, 30, True), (1080, 1080, 180, True), (1920, 1080, 30, False), (1080, 1920, 240, False)])
def test_check_short(w, h, d, ok):
    with mock.patch.object(shorts, "probe", return_value={"width": w, "height": h, "duration": d}):
        good, msg = shorts.check_short("x.mp4")
    assert good == ok and (ok or msg.startswith("Not a Short"))

def test_unreadable_is_warning():
    with mock.patch.object(shorts, "probe", side_effect=ValueError("bad")):
        ok, msg = shorts.check_short("x.mp4")
    assert ok and msg.startswith("warning")

def test_upload_rejects_landscape(tmp_path):
    with mock.patch.object(shorts, "probe", return_value={"width": 1920, "height": 1080, "duration": 10}):
        with pytest.raises(RuntimeError, match="Not a Short"): youtube.upload(tmp_path / "v.mp4", "t", "c")

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg to create sample files")
@pytest.mark.parametrize("size,ok", [("360x640", True), ("640x360", False)])
def test_real_files_ffprobe_and_mp4_parser(tmp_path, size, ok):
    f = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=blue:s={size}:d=2", "-pix_fmt", "yuv420p", str(f)], check=True)
    w, h = map(int, size.split("x"))
    for fn in (shorts._ffprobe, shorts._mp4):
        m = fn(f); assert (m["width"], m["height"]) == (w, h) and 1.5 < m["duration"] < 2.5
    assert shorts.check_short(f)[0] == ok
