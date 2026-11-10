"""Pure helpers for ingest: find which local file belongs to which film, probe it, estimate transcode cost."""
import json
import re
import subprocess
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".ogv"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_files(films, media_dir):
    """Map film id -> file. A file matches when its normalised name contains the film id or title.

    Exact `<id>.<ext>` wins; otherwise the LONGEST matching key wins (so "caminandes-llama-drama" beats
    a hypothetical "caminandes"). Returns (matches, unmatched_files).
    """
    files = sorted(p for p in Path(media_dir).glob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT)
    keys = [(f["id"], norm(f["id"])) for f in films] + [(f["id"], norm(f["title"])) for f in films]
    # "Caminandes: Llama Drama" is often saved as "Caminandes 3 - Llama Drama", so also try the SUBTITLE (the part
    # after the colon). Never the part before it: that is a series name ("Caminandes") shared by several films.
    for f in films:
        keys += [(f["id"], norm(part)) for part in f["title"].split(":")[1:] if len(norm(part)) >= 8]
    matches, unmatched = {}, []
    for p in files:
        stem = norm(p.stem)
        best = None
        for fid, k in keys:
            if k and k in stem and (best is None or len(k) > best[1]):
                best = (fid, len(k))
        if best is None:
            unmatched.append(p)
        elif best[0] in matches:
            # two files for one film: keep the larger (usually the higher-quality one)
            if p.stat().st_size > matches[best[0]].stat().st_size:
                matches[best[0]] = p
        else:
            matches[best[0]] = p
    return matches, unmatched


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {"duration": float(d["format"]["duration"]), "width": int(v["width"]), "height": int(v["height"]),
            "size": int(d["format"]["size"])}


# ---- cost model (all figures are ESTIMATES; the first real run replaces them in COSTS.md) ----
# Fargate ARM64 prices per hour. us-east-2 is not published on the pricing page I could read, so these are
# the N. Virginia on-demand rates (us-east-2 is normally identical). Spot discount is NOT verified, so
# the headline number is the on-demand price and Spot is reported only as "likely cheaper".
VCPU_HR, GB_HR, TASK_VCPU, TASK_GB = 0.03238, 0.00356, 4, 8
PUBLIC_IP_HR = 0.005
OVERHEAD_MIN = 2.0                      # image pull + download + upload + startup per film
SPEED_LOW, SPEED_HIGH = 1.5, 0.5        # encode speed vs. realtime for 4 x264 renditions on 4 Graviton vCPUs
OUT_MBPS = 11.7                         # sum of the ladder's video+audio bitrates (360p..1080p)
S3_GB_MONTH = 0.023


def task_rate_per_hour():
    return TASK_VCPU * VCPU_HR + TASK_GB * GB_HR + PUBLIC_IP_HR


def estimate(films_info):
    """films_info: list of dicts with duration (sec) and size (bytes). Returns totals + a (low, high) cost range."""
    total_sec = sum(f["duration"] for f in films_info)
    rate = task_rate_per_hour()

    def run_hours(speed):
        return sum(f["duration"] / speed / 3600 + OVERHEAD_MIN / 60 for f in films_info)

    low, high = run_hours(SPEED_LOW) * rate, run_hours(SPEED_HIGH) * rate
    out_gb = OUT_MBPS * total_sec / 8 / 1000
    src_gb = sum(f["size"] for f in films_info) / 1e9
    storage_month = (out_gb + src_gb) * S3_GB_MONTH
    other = len(films_info) * 0.001      # Step Functions transitions, Lambda, EventBridge: fractions of a cent each
    return {
        "films": len(films_info), "content_minutes": total_sec / 60, "task_rate_hr": rate,
        "compute_low": low, "compute_high": high, "other": other,
        "total_low": low + other, "total_high": high + other,
        "run_hours_low": run_hours(SPEED_LOW), "run_hours_high": run_hours(SPEED_HIGH),
        "output_gb": out_gb, "source_gb": src_gb, "storage_per_month": storage_month,
    }
