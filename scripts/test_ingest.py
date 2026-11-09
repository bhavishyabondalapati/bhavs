import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "ingest"))
import media

FILMS = [
    {"id": "sintel", "title": "Sintel"},
    {"id": "big-buck-bunny", "title": "Big Buck Bunny"},
    {"id": "agent-327", "title": "Agent 327: Operation Barbershop"},
    {"id": "caminandes-llama-drama", "title": "Caminandes: Llama Drama"},
]


def touch(d, name, size=1):
    (d / name).write_bytes(b"x" * size)


def test_matches_messy_filenames(tmp_path):
    touch(tmp_path, "Sintel.2010.1080p.mkv")
    touch(tmp_path, "big_buck_bunny_1080p_h264.mov")
    touch(tmp_path, "Agent327-OperationBarbershop.mp4")
    touch(tmp_path, "Caminandes 3 - Llama Drama.mp4")
    touch(tmp_path, "random-holiday.mp4")
    touch(tmp_path, "notes.txt")
    m, un = media.match_files(FILMS, tmp_path)
    assert set(m) == {"sintel", "big-buck-bunny", "agent-327", "caminandes-llama-drama"}
    assert [p.name for p in un] == ["random-holiday.mp4"]


def test_duplicate_keeps_larger_file(tmp_path):
    touch(tmp_path, "sintel_720p.mp4", 10)
    touch(tmp_path, "sintel_1080p.mp4", 99)
    m, _ = media.match_files(FILMS, tmp_path)
    assert m["sintel"].name == "sintel_1080p.mp4"


def test_estimate_scales_with_duration():
    one = media.estimate([{"duration": 600, "size": 5e8}])
    two = media.estimate([{"duration": 600, "size": 5e8}] * 2)
    assert 0 < one["total_low"] < one["total_high"]
    assert abs(two["compute_high"] - 2 * one["compute_high"]) < 1e-9
    assert one["total_high"] < 1.0          # a 10-minute film must cost well under a dollar


def test_rate_matches_published_arm_prices():
    assert abs(media.task_rate_per_hour() - (4 * 0.03238 + 8 * 0.00356 + 0.005)) < 1e-12
