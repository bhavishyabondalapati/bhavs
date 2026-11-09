import json

from api import continue_watching, events, me, recommendations, titles_get, titles_list
from conftest import api_event


def body(r):
    return json.loads(r["body"])


def test_list_hides_failed_and_internal_fields(db):
    r = titles_list.handler(api_event(), None)
    ids = [t["id"] for t in body(r)["titles"]]
    assert r["statusCode"] == 200
    assert ids == ["sintel", "bbb"]  # newest first, FAILED hidden
    assert "secret_internal" not in body(r)["titles"][0]


def test_get_title_and_404(db):
    assert titles_get.handler(api_event(path={"id": "bbb"}), None)["statusCode"] == 200
    assert titles_get.handler(api_event(path={"id": "nope"}), None)["statusCode"] == 404


def test_me_reports_admin_group(db):
    r = me.handler(api_event(groups="[admin]"), None)
    assert body(r)["is_admin"] is True
    assert body(me.handler(api_event(uid="u2"), None))["is_admin"] is False


def test_events_validation(db):
    assert events.handler(api_event(body={"type": "bogus", "title_id": "bbb", "position": 1}), None)["statusCode"] == 400
    assert events.handler(api_event(body={"type": "play", "title_id": "bbb", "position": -3}), None)["statusCode"] == 400
    assert events.handler(api_event(body={"type": "play", "title_id": "ghost", "position": 1}), None)["statusCode"] == 404


def test_resume_and_completion_flow(db):
    ev = lambda t, pos, dur=600: api_event(body={"type": t, "title_id": "bbb", "position": pos, "duration": dur})
    assert events.handler(ev("heartbeat", 120), None)["statusCode"] == 202
    cw = body(continue_watching.handler(api_event(), None))["items"]
    assert [i["title"]["id"] for i in cw] == ["bbb"] and cw[0]["position"] == 120
    events.handler(ev("heartbeat", 590), None)  # 98% -> finished
    assert body(continue_watching.handler(api_event(), None))["items"] == []


def test_recommendations_cold_start_then_global_then_personal(db):
    r = body(recommendations.handler(api_event(), None))
    assert r["cold_start"] and r["rows"][0]["key"] == "latest"
    recs = db.Table("recs")
    recs.put_item(Item={"user_id": "GLOBAL", "row_key": "popular", "label": "Popular", "rank": 1, "title_ids": ["bbb"]})
    r = body(recommendations.handler(api_event(), None))
    assert r["cold_start"] and r["rows"][0]["label"] == "Popular"
    recs.put_item(Item={"user_id": "u1", "row_key": "top", "label": "Top picks for you", "rank": 1, "title_ids": ["sintel"]})
    r = body(recommendations.handler(api_event(), None))
    assert not r["cold_start"] and r["rows"][0]["titles"][0]["id"] == "sintel"
