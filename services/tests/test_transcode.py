import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "transcode"))
import transcode as tc

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_ladder_never_upscales():
    assert [r[0] for r in tc.pick_ladder(1920)] == ["360p", "540p", "720p", "1080p"]
    assert [r[0] for r in tc.pick_ladder(1280)] == ["360p", "540p", "720p"]
    assert [r[0] for r in tc.pick_ladder(300)] == ["360p"]  # always at least one rung


def test_widescreen_film_still_gets_1080p_rung():
    info = {"width": 1920, "height": 800, "fps": 24.0, "duration": 60, "has_audio": True}
    rungs = tc.pick_ladder(info["width"])
    assert rungs[-1][0] == "1080p"
    assert "RESOLUTION=1920x800" in tc.master_playlist(rungs, info)


def test_ffmpeg_args_one_decode_many_outputs(tmp_path):
    info = {"width": 1920, "height": 1080, "fps": 24.0, "duration": 600, "has_audio": True}
    args = tc.ffmpeg_args("in.mp4", tmp_path, info, tc.pick_ladder(1920))
    assert args.count("-i") == 1  # decode the source once
    assert args.count("libx264") == 4
    assert "split=4" in args[args.index("-filter_complex") + 1]
    assert "-sc_threshold" in args and "independent_segments" in args


def test_no_audio_source_has_no_audio_maps(tmp_path):
    info = {"width": 640, "height": 360, "fps": 24.0, "duration": 5, "has_audio": False}
    args = tc.ffmpeg_args("in.mp4", tmp_path, info, tc.pick_ladder(640))
    assert "aac" not in args and "0:a:0" not in args


def test_master_playlist_lists_each_rung():
    info = {"width": 1920, "height": 1080, "fps": 24.0, "duration": 60, "has_audio": True}
    m = tc.master_playlist(tc.pick_ladder(1920), info)
    assert m.count("#EXT-X-STREAM-INF") == 4 and "RESOLUTION=1920x1080" in m and "360p/index.m3u8" in m


def test_sprite_vtt_tiles():
    vtt = tc.sprite_vtt(25)
    assert vtt.startswith("WEBVTT") and "sprite.jpg#xywh=0,0,160,90" in vtt and "xywh=320,0,160,90" in vtt


@needs_ffmpeg
def test_real_transcode_of_synthetic_clip(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=14",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=14", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
    out = tmp_path / "out"
    m = tc.transcode(src, out, "demo")
    assert m["duration_sec"] == 14
    assert [r["name"] for r in m["renditions"]] == ["360p", "540p", "720p"]  # 720p source: no 1080p
    for f in ("master.m3u8", "poster.jpg", "sprite.jpg", "sprite.vtt", "manifest.json", "720p/index.m3u8"):
        assert (out / f).exists(), f
    assert len(list((out / "360p").glob("seg_*.ts"))) >= 2
    assert json.loads((out / "manifest.json").read_text())["title_id"] == "demo"
