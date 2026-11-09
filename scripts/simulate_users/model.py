"""Synthetic viewers for bhavs. EVERYTHING produced here is SYNTHETIC and labelled so:
users are `synthetic-0001`..., every event has synthetic=true, every DynamoDB row has synthetic=true.

The generator is a pure, seeded function so results are reproducible and unit-testable. The behaviour is
deliberately structured (taste clusters, genre preferences, popularity skew, evening peaks, network quality)
so the analytics have real patterns to show and the recommenders have a signal to learn.
"""
import math
import random
from dataclasses import dataclass, field

HEARTBEAT_S = 15
# (name, bandwidth kbit/s as declared in the HLS master playlist)
LADDER = [("360p", 1008), ("540p", 2108), ("720p", 3428), ("1080p", 5628)]
EVENING_HOURS = [17, 18, 19, 20, 21, 22, 23]       # UTC; weights below favour the late evening
EVENING_WEIGHTS = [1, 2, 3, 5, 6, 6, 4]
N_CLUSTERS = 5


@dataclass
class User:
    user_id: str
    cluster: int
    genre_weights: dict
    activity: float          # expected sessions in the window
    mbps: float              # typical network speed


@dataclass
class State:
    position: float = 0.0
    completed: bool = False
    plays: int = 0
    max_pct: float = 0.0
    updated_at: int = 0


@dataclass
class Result:
    users: list = field(default_factory=list)
    events: list = field(default_factory=list)
    history: list = field(default_factory=list)


def make_users(n, genres, rng):
    users = []
    for i in range(1, n + 1):
        favs = rng.sample(genres, k=min(len(genres), rng.choice([1, 2, 2, 3])))
        weights = {g: (rng.uniform(1.5, 3.0) if g in favs else rng.uniform(0.2, 0.8)) for g in genres}
        users.append(User(f"synthetic-{i:04d}", rng.randrange(N_CLUSTERS), weights,
                          activity=max(1.0, rng.lognormvariate(math.log(9), 0.7)),
                          mbps=rng.lognormvariate(math.log(12), 1.0)))
    return users


def affinity_table(titles, users, rng):
    """affinity[user_id][title_id] in (0, ~4): popularity skew x cluster taste x personal genre taste."""
    pop = {t["id"]: 1.0 / (rank + 1) ** 0.9 for rank, t in enumerate(rng.sample(titles, len(titles)))}
    cluster_likes = [set(rng.sample([t["id"] for t in titles], k=max(2, len(titles) // 3))) for _ in range(N_CLUSTERS)]
    table = {}
    for u in users:
        row = {}
        for t in titles:
            g = sum(u.genre_weights.get(x, 0.3) for x in t.get("genres", [])) / max(1, len(t.get("genres", [])))
            row[t["id"]] = pop[t["id"]] * g * (2.2 if t["id"] in cluster_likes[u.cluster] else 1.0)
        table[u.user_id] = row
    return table


def pick_rung(mbps, rng, prev=None):
    best = 0
    for i, (_, kbps) in enumerate(LADDER):
        if kbps * 1.4 / 1000 <= mbps:
            best = i
    if prev is not None and rng.random() < 0.9:   # ABR is sticky; occasionally it steps
        return prev
    return max(0, min(len(LADDER) - 1, best + rng.choice([-1, 0, 0, 0, 1])))


def simulate_session(user, title, start_ts, resume, p_abandon, rng):
    """One viewing session -> (events, final position, finished). Times are epoch milliseconds."""
    dur = float(title["duration_sec"])
    sid = f"sim-{rng.getrandbits(48):012x}"
    finished = rng.random() >= p_abandon
    stop = dur if finished else max(5.0, min(dur - 1, dur * rng.betavariate(1.3, 3.5)))
    pos = float(resume) if resume < stop - 5 else 0.0
    t = start_ts
    rung = pick_rung(user.mbps, rng)
    out = []

    def ev(kind):
        name, kbps = LADDER[rung]
        out.append({"ts": int(t), "received_at": int(t), "type": kind, "user_id": user.user_id, "title_id": title["id"],
                    "session_id": sid, "position": round(pos, 1), "duration": dur,
                    "bitrate_kbps": kbps, "rendition": name, "synthetic": True})

    ev("play")
    since_hb = 0.0
    seeks_left = rng.choice([0, 0, 0, 1, 1, 2])
    while pos < stop:
        step = min(HEARTBEAT_S - since_hb, stop - pos)
        pos += step
        t += step * 1000
        since_hb += step
        if since_hb >= HEARTBEAT_S - 1e-9 and pos < stop:
            rung = pick_rung(user.mbps, rng, rung)
            ev("heartbeat")
            since_hb = 0.0
            r = rng.random()
            if seeks_left and r < 0.04:                      # seek forward or back
                pos = max(0.0, min(stop - 1, pos + rng.choice([-60, -30, 30, 60, 120])))
                seeks_left -= 1
                ev("seek")
            elif r < 0.07:                                   # pause then resume
                ev("pause")
                t += rng.uniform(5, 120) * 1000
                ev("play")
    pos = dur if finished else pos
    ev("complete" if finished else "pause")
    return out, (0.0 if finished else pos), finished


def simulate(titles, n_users=200, days=10, seed=42, end_ts=None):
    """titles: dicts with id, genres, duration_sec. end_ts: epoch seconds; sessions fall in the `days` before it."""
    rng = random.Random(seed)
    genres = sorted({g for t in titles for g in t.get("genres", [])})
    users = make_users(n_users, genres, rng)
    aff = affinity_table(titles, users, rng)
    res = Result(users=users)
    end_ts = int(end_ts)
    by_id = {t["id"]: t for t in titles}
    max_aff = max(a for row in aff.values() for a in row.values())

    for u in users:
        n = max(1, round(rng.gauss(u.activity, u.activity * 0.3)))
        starts = []
        for _ in range(n):
            day = rng.randrange(days)
            hour = rng.choices(EVENING_HOURS, EVENING_WEIGHTS)[0]
            base = (end_ts // 86400 - day - 1) * 86400
            starts.append((base + hour * 3600 + rng.randrange(3600)) * 1000)
        state = {}
        for start in sorted(starts):
            ids = list(aff[u.user_id])
            w = []
            for tid in ids:
                s = state.get(tid)
                w.append(aff[u.user_id][tid] * (0.15 if s and s.completed else 1.0))
            tid = rng.choices(ids, w)[0]
            title = by_id[tid]
            st = state.setdefault(tid, State())
            a = aff[u.user_id][tid] / max_aff
            p_abandon = min(0.8, max(0.05, 0.7 - 0.9 * a))
            resume = st.position if (st.position > 5 and rng.random() < 0.7) else 0.0
            events, final_pos, finished = simulate_session(u, title, start, resume, p_abandon, rng)
            res.events.extend(events)
            st.plays += 1
            st.position, st.completed = final_pos, st.completed or finished
            st.max_pct = max(st.max_pct, max(e["position"] for e in events) / title["duration_sec"])
            st.updated_at = events[-1]["ts"] // 1000
        for tid, st in state.items():
            res.history.append({"user_id": u.user_id, "title_id": tid, "position": round(st.position, 1),
                                "duration": by_id[tid]["duration_sec"], "completed": st.completed,
                                "plays": st.plays, "max_pct": round(min(1.0, st.max_pct), 3),
                                "updated_at": st.updated_at, "synthetic": True})
    res.events.sort(key=lambda e: e["ts"])
    return res
