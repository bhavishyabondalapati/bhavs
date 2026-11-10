import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import record_sources as rs

SAMPLE = """# header comment
films:
  - id: a
    title: A
    credit: "x"
  - id: b
    title: B
    source:
      url: old
      page: old
    credit: "y"
"""


def test_inserts_and_replaces_without_touching_comments():
    rows = {"a": {"url": "http://u/a", "page": "http://p/a", "license": "CC BY 3.0", "size": "10", "date": "2026-11-09"},
            "b": {"url": "http://u/b", "page": "http://p/b", "license": "CC BY 4.0", "size": "20", "date": "2026-11-09"}}
    out = rs.record(SAMPLE, rows)
    assert out.startswith("# header comment")
    d = yaml.safe_load(out)["films"]
    assert d[0]["source"]["url"] == "http://u/a" and d[0]["credit"] == "x"
    assert d[1]["source"]["url"] == "http://u/b" and d[1]["credit"] == "y" and out.count("\n    source:") == 2


def test_idempotent():
    rows = {"a": {"url": "u", "page": "p", "license": "L", "size": "1", "date": "d"}}
    once = rs.record(SAMPLE, rows)
    assert rs.record(once, rows) == once


def test_real_films_yaml_still_parses():
    root = Path(__file__).resolve().parent.parent
    text = (root / "films.yaml").read_text()
    assert len(yaml.safe_load(rs.record(text, {}))["films"]) >= 8


def test_films_not_in_this_run_keep_their_source():
    rows = {"a": {"url": "http://u/a", "page": "http://p/a", "license": "L", "size": "1", "date": "d"}}
    out = rs.record(SAMPLE, rows)          # b is NOT in rows: its existing source block must survive untouched
    d = yaml.safe_load(out)["films"]
    assert d[1]["source"]["url"] == "old" and d[0]["source"]["url"] == "http://u/a"
