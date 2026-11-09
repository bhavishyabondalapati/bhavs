"""bhavs transcoder: one source video -> HLS ladder (360p/540p/720p/1080p) + poster + sprite + manifest.

Runs in two places with the SAME code:
  * ECS Fargate (entrypoint, reads S3 via env vars)           -> python transcode.py
  * your Mac (make transcode-local, free fallback)             -> python transcode.py --src f.mp4 --out ./out

ffmpeg decodes the source ONCE and feeds every rendition (split filter), so cost is roughly one
decode + four encodes, not four separate jobs.
"""
import argparse
import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEGMENT_SECONDS = 6
SPRITE_EVERY = 10          # one thumbnail per N seconds
SPRITE_W, SPRITE_H, SPRITE_COLS = 160, 90, 10

# name, frame WIDTH, video kbit/s, h264 level (for the CODECS string). Names are the 16:9 class; we scale by
# WIDTH so widescreen films (e.g. 1920x800) still get a full "1080p" rung without being upscaled.
LADDER = [
    ("360p", 640, 800, "1e"),
    ("540p", 960, 1800, "1f"),
    ("720p", 1280, 3000, "1f"),
    ("1080p", 1920, 5000, "28"),
]
AUDIO_KBPS = 128


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("no video stream")
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {
        "width": int(video["width"]), "height": int(video["height"]), "fps": fps or 24.0,
        "duration": float(data["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }


def pick_ladder(src_width):
    """Never upscale: keep renditions no wider than the source (always at least the smallest)."""
    rungs = [r for r in LADDER if r[1] <= src_width + 8]
    return rungs or LADDER[:1]


def ffmpeg_args(src, out_dir, info, rungs):
    """Build the single ffmpeg command that writes every rendition."""
    fps = min(info["fps"], 30.0)
    gop = max(1, round(fps * SEGMENT_SECONDS))
    n = len(rungs)
    labels = "".join(f"[v{i}]" for i in range(n))
    chains = ";".join(f"[v{i}]scale={w}:-2:flags=bicubic,format=yuv420p[o{i}]" for i, (_, w, _, _) in enumerate(rungs))
    head = "fps=30," if info["fps"] > 30.5 else ""
    graph = f"[0:v]{head}split={n}{labels};{chains}"
    args = ["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-filter_complex", graph]
    for i, (name, _h, kbps, _lvl) in enumerate(rungs):
        d = Path(out_dir) / name
        d.mkdir(parents=True, exist_ok=True)
        args += ["-map", f"[o{i}]"]
        if info["has_audio"]:
            args += ["-map", "0:a:0"]
        args += [
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
            "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.1)}k", "-bufsize", f"{kbps * 2}k",
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})",
        ]
        if info["has_audio"]:
            args += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2", "-ar", "48000"]
        args += [
            "-f", "hls", "-hls_time", str(SEGMENT_SECONDS), "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(d / "seg_%04d.ts"), str(d / "index.m3u8"),
        ]
    return args


def master_playlist(rungs, info):
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    audio = AUDIO_KBPS if info["has_audio"] else 0
    for name, w, kbps, lvl in rungs:
        h = round(info["height"] * w / info["width"] / 2) * 2
        codecs = f"avc1.6400{lvl}" + (",mp4a.40.2" if info["has_audio"] else "")
        bw = int((kbps * 1.1 + audio) * 1000)
        lines += [f'#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={w}x{h},CODECS="{codecs}",NAME="{name}"', f"{name}/index.m3u8"]
    return "\n".join(lines) + "\n"


def _ts(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.000"


def sprite_vtt(duration):
    """WebVTT mapping each time range to a tile in sprite.jpg (for seek-bar previews)."""
    cues = ["WEBVTT", ""]
    count = max(1, math.ceil(duration / SPRITE_EVERY))
    for i in range(count):
        x, y = (i % SPRITE_COLS) * SPRITE_W, (i // SPRITE_COLS) * SPRITE_H
        cues += [f"{_ts(i * SPRITE_EVERY)} --> {_ts(min((i + 1) * SPRITE_EVERY, math.ceil(duration)))}",
                 f"sprite.jpg#xywh={x},{y},{SPRITE_W},{SPRITE_H}", ""]
    return "\n".join(cues)


def make_images(src, out_dir, info, rung_dir):
    """Poster at ~10% in, and a thumbnail sprite sheet built from the (cheap to decode) lowest rendition."""
    at = max(1.0, info["duration"] * 0.10)
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1",
                    "-vf", "scale=1280:-2", "-q:v", "3", str(Path(out_dir) / "poster.jpg")], check=True, capture_output=True)
    count = max(1, math.ceil(info["duration"] / SPRITE_EVERY))
    rows = math.ceil(count / SPRITE_COLS)
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", str(Path(rung_dir) / "index.m3u8"), "-an",
                    "-vf", (f"fps=1/{SPRITE_EVERY},scale={SPRITE_W}:{SPRITE_H}:force_original_aspect_ratio=increase,"
                            f"crop={SPRITE_W}:{SPRITE_H},tile={SPRITE_COLS}x{rows}"),
                    "-frames:v", "1", "-q:v", "5", str(Path(out_dir) / "sprite.jpg")], check=True, capture_output=True)
    (Path(out_dir) / "sprite.vtt").write_text(sprite_vtt(info["duration"]))


def transcode(src, out_dir, title_id):
    """Run the whole job locally; returns the manifest dict (also written to manifest.json)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    rungs = pick_ladder(info["width"])
    subprocess.run(ffmpeg_args(src, out_dir, info, rungs), check=True)
    (out_dir / "master.m3u8").write_text(master_playlist(rungs, info))
    make_images(src, out_dir, info, out_dir / rungs[0][0])
    manifest = {
        "title_id": title_id,
        "duration_sec": round(info["duration"]),
        "hls": "master.m3u8", "poster": "poster.jpg", "sprite": "sprite.jpg", "sprite_vtt": "sprite.vtt",
        "renditions": [{"name": n, "width": w, "video_kbps": k} for n, w, k, _ in rungs],
        "source": {"width": info["width"], "height": info["height"], "fps": round(info["fps"], 2)},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


CACHE = {".m3u8": "public, max-age=60", ".vtt": "public, max-age=3600", ".json": "no-cache"}


def upload_dir(s3, bucket, prefix, out_dir):
    """Upload everything; manifest.json goes LAST so its presence means the job is complete."""
    files = sorted(p for p in Path(out_dir).rglob("*") if p.is_file() and p.name != "manifest.json")
    files.append(Path(out_dir) / "manifest.json")
    for p in files:
        key = f"{prefix}{p.relative_to(out_dir).as_posix()}"
        ctype = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t"}.get(p.suffix) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        s3.upload_file(str(p), bucket, key, ExtraArgs={"ContentType": ctype, "CacheControl": CACHE.get(p.suffix, "public, max-age=31536000, immutable")})


def run_in_fargate():
    import boto3
    s3 = boto3.client("s3")
    e = os.environ
    title_id, prefix = e["TITLE_ID"], e["OUT_PREFIX"]
    work = Path(tempfile.mkdtemp(prefix="bhavs-"))
    try:
        src = work / "source"
        print(f"downloading s3://{e['SRC_BUCKET']}/{e['SRC_KEY']}", flush=True)
        s3.download_file(e["SRC_BUCKET"], e["SRC_KEY"], str(src))
        out = work / "out"
        manifest = transcode(src, out, title_id)
        print(f"transcoded {manifest['duration_sec']}s, renditions={[r['name'] for r in manifest['renditions']]}", flush=True)
        upload_dir(s3, e["OUT_BUCKET"], prefix, out)
        print("uploaded", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--out")
    ap.add_argument("--title-id", default="local")
    a = ap.parse_args()
    if a.src:
        m = transcode(a.src, a.out, a.title_id)
        print(json.dumps(m, indent=2))
    else:
        try:
            run_in_fargate()
        except Exception as exc:  # noqa: BLE001  # non-zero exit tells ECS/Step Functions the task failed
            print(f"FAILED: {exc!r}", file=sys.stderr, flush=True)
            sys.exit(1)
