"""YouTube Shorts helpers: #Shorts tagging and vertical/<=180 s validation."""
import json, mmap, re, shutil, struct, subprocess
from pathlib import Path

MAX_SECONDS = 180
TAG = "#Shorts"
_HAS = re.compile(r"(?<!\w)#shorts\b", re.I)

def tag_title(title: str) -> str:
    title = (title or "Untitled").strip()
    if _HAS.search(title): return title[:100]
    return f"{title} {TAG}" if len(title) + 1 + len(TAG) <= 100 else title[:100]

def tag_description(desc: str) -> str:
    desc = (desc or "").strip()
    if _HAS.search(desc): return desc[:5000]
    return (f"{desc}\n\n{TAG}" if desc else TAG)[-5000:] if len(desc) + 9 > 5000 else (f"{desc}\n\n{TAG}" if desc else TAG)

def _ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:stream_tags=rotate:stream_side_data=rotation:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60)
    if out.returncode: raise ValueError(out.stderr.strip() or "ffprobe failed")
    d = json.loads(out.stdout); s = d["streams"][0]
    w, h = int(s["width"]), int(s["height"])
    rot = s.get("tags", {}).get("rotate") or next((sd.get("rotation") for sd in s.get("side_data_list", []) if "rotation" in sd), 0)
    if abs(int(float(rot or 0))) % 180 == 90: w, h = h, w
    return {"width": w, "height": h, "duration": float(d["format"]["duration"])}

def _mp4(path):
    """Minimal MP4/MOV parser: mvhd duration + first video tkhd size (+90° rotation matrix)."""
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:  # no full read into RAM
        return _parse_mp4(data)

def _parse_mp4(data):
    res = {}
    def walk(b, s, e):
        while s + 8 <= e:
            size, typ = struct.unpack(">I4s", b[s:s+8]); hdr = 8
            if size == 1: size = struct.unpack(">Q", b[s+8:s+16])[0]; hdr = 16
            elif size == 0: size = e - s
            if size < hdr: break
            body = s + hdr
            if typ in (b"moov", b"trak"): walk(b, body, s + size)
            elif typ == b"mvhd":
                v = b[body]
                ts, dur = struct.unpack(">IQ", b[body+20:body+32]) if v == 1 else struct.unpack(">II", b[body+12:body+20])
                res["duration"] = dur / ts if ts else 0
            elif typ == b"tkhd" and "width" not in res:
                w, h = struct.unpack(">II", b[s+size-8:s+size]); w, h = w >> 16, h >> 16
                if w and h:
                    a, bb = struct.unpack(">ii", b[s+size-44:s+size-36])
                    if a == 0 and bb != 0: w, h = h, w   # rotated 90/270
                    res["width"], res["height"] = w, h
            s += size
    walk(data, 0, len(data))
    if not {"width", "height", "duration"} <= res.keys(): raise ValueError("could not read MP4 metadata")
    return res

def probe(path):
    if shutil.which("ffprobe"): return _ffprobe(path)
    return _mp4(path)

def check_short(path):
    """Return (ok, message). If metadata can't be read, allow upload with a warning."""
    try: m = probe(path)
    except Exception as e: return True, f"warning: could not check video ({e}); uploading anyway"
    problems = []
    if m["height"] < m["width"]: problems.append(f"it's horizontal ({m['width']}x{m['height']})")
    if m["duration"] > MAX_SECONDS + 0.5: problems.append(f"it's {m['duration']:.0f}s long")
    if problems: return False, "Not a Short: must be vertical/square and 3 min or less – " + " and ".join(problems)
    return True, f"ok ({m['width']}x{m['height']}, {m['duration']:.0f}s)"
