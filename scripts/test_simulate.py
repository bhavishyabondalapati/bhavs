import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "simulate_users"))
import itertools

import model

TITLES = [{"id": f"t{i}", "genres": g, "duration_sec": d} for i, (g, d) in enumerate([
    (["comedy", "animation"], 600), (["sci-fi"], 700), (["fantasy", "animation"], 900), (["comedy"], 120),
    (["sci-fi", "action"], 800), (["animation"], 300), (["fantasy"], 500), (["action"], 650)])]
NOW = 1_800_000_000


def run(seed=7, users=60):
    return model.simulate(TITLES, users, 5, seed, end_ts=NOW)


def test_deterministic_for_a_seed():
    a, b = run(), run()
    assert [e["ts"] for e in a.events] == [e["ts"] for e in b.events]
    assert run(seed=8).events != a.events


def test_everything_is_labelled_synthetic():
    r = run()
    assert all(u.user_id.startswith("synthetic-") for u in r.users)
    assert all(e["synthetic"] is True and e["user_id"].startswith("synthetic-") for e in r.events)
    assert all(h["synthetic"] is True for h in r.history)


def test_event_invariants():
    r = run()
    by_id = {t["id"]: t for t in TITLES}
    for e in r.events:
        assert 0 <= e["position"] <= by_id[e["title_id"]]["duration_sec"] + 1e-6
        assert e["type"] in {"play", "pause", "seek", "heartbeat", "complete"}
        assert e["ts"] // 1000 <= NOW
    sessions = {}
    for e in r.events:
        sessions.setdefault(e["session_id"], []).append(e)
    for evs in sessions.values():
        assert evs[0]["type"] == "play"
        assert evs[-1]["type"] in ("complete", "pause")
        assert all(a["ts"] <= b["ts"] for a, b in itertools.pairwise(evs))


def test_behaviour_has_variety():
    r = run(users=120)
    sessions = {e["session_id"] for e in r.events}
    done = sum(e["type"] == "complete" for e in r.events)
    assert 0.2 < done / len(sessions) < 0.9                       # neither everyone finishes nor everyone quits
    assert {e["rendition"] for e in r.events} >= {"360p", "1080p"}   # varied network quality
    hours = {time.gmtime(e["ts"] / 1000).tm_hour for e in r.events}
    assert hours <= set(range(17, 24)) or len(hours) > 3            # evening-weighted (pauses can spill past midnight)
    per_user = {}
    for h in r.history:
        per_user.setdefault(h["user_id"], set()).add(h["title_id"])
    assert len({len(v) for v in per_user.values()}) > 3            # users differ in how much they watch


def test_users_prefer_their_taste():
    r = run(users=200)
    counts = {}
    for h in r.history:
        counts[h["title_id"]] = counts.get(h["title_id"], 0) + h["plays"]
    assert max(counts.values()) > 2 * min(counts.values())          # popularity skew exists
