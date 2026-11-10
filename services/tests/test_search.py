"""Search tests use a fake embedder (words -> vector slots) so ranking is checkable without calling Bedrock."""
import json

import boto3
import pytest
from api import search
from conftest import api_event
from moto import mock_aws
from shared import embed

VOCAB = ["dragon", "warrior", "rabbit", "forest", "coffee", "space"]


def fake_embed(text):
    words = text.lower().replace(".", " ").split()
    v = [float(words.count(w)) for w in VOCAB]
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


@pytest.fixture
def index(db, monkeypatch):
    monkeypatch.setattr(embed, "embed", fake_embed)
    monkeypatch.setenv("ANALYTICS_BUCKET", "lake")
    monkeypatch.setenv("EMBEDDINGS_KEY", "search/embeddings.json")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    docs = [{"id": "sintel", "title": "Sintel", "text": "Genres: fantasy. A lone warrior and a small dragon.",
             "vector": fake_embed("warrior dragon")},
            {"id": "bbb", "title": "Big Buck Bunny", "text": "Genres: comedy. A giant rabbit plans payback on bullies.",
             "vector": fake_embed("rabbit forest")},
            {"id": "broken", "title": "Broken", "text": "Genres: sci-fi.", "vector": fake_embed("space")}]
    s3.put_object(Bucket="lake", Key="search/embeddings.json", Body=json.dumps({"items": docs}))
    search._index.update(at=0.0, items=[])
    search._query_cache.clear()
    yield


def run(q):
    r = search.handler({**api_event(), "queryStringParameters": {"q": q}}, None)
    return r["statusCode"], json.loads(r["body"])


def test_ranks_by_meaning_and_hides_failed(index):
    code, body = run("a dragon")
    assert code == 200 and [t["id"] for t in body["results"]] == ["sintel"]
    _, body = run("space")  # only match is a FAILED title, which must not appear
    assert body["results"] == []


def test_title_substring_wins(index):
    _, body = run("buck")
    assert body["results"][0]["id"] == "bbb" and body["results"][0]["score"] == 1.0


def test_title_match_does_not_hide_related_titles(index):
    _, body = run("sintel warrior")  # no title contains this; pure semantic
    assert [t["id"] for t in body["results"]] == ["sintel"]
    search.MIN_SCORE, old = 0.0, search.MIN_SCORE
    try:
        named, related = search.rank("sintel", [{"id": "sintel", "title": "Sintel", "vector": [1.0, 0.0]},
                                                {"id": "other", "title": "Other", "vector": [0.9, 0.1]}], [1.0, 0.0])
    finally:
        search.MIN_SCORE = old
    assert named == (1.0, "sintel") and related[1] == "other"


def test_unrelated_query_returns_nothing(index):
    assert run("pasta recipe")[1]["results"] == []


def test_validation(index):
    assert run("a")[0] == 400
    assert run("x" * 201)[0] == 400


def test_missing_index_is_503(db, monkeypatch):
    with mock_aws():
        monkeypatch.setenv("ANALYTICS_BUCKET", "nope")
        monkeypatch.setenv("EMBEDDINGS_KEY", "k")
        search._index.update(at=0.0, items=[])
        assert run("dragon")[0] == 503


def test_keywords_find_what_meaning_misses(index):
    # "payback" and "bullies" are not in the fake embedder's vocabulary, so only BM25 can find Big Buck Bunny.
    _, body = run("payback on the bullies")
    assert [t["id"] for t in body["results"]] == ["bbb"]


def test_bm25_stemming_and_stopwords():
    from shared import textsearch
    assert textsearch.tokenize("The Robots and dragons") == ["robot", "dragon"]
    items = [{"id": "a", "title": "A", "text": "robot war"}, {"id": "b", "title": "B", "text": "quiet garden"}]
    assert set(textsearch.bm25_scores("robots", items)) == {"a"}
    assert textsearch.bm25_scores("the and of", items) == {}


def test_titan_request_shape(monkeypatch):
    """The exact body sent to Bedrock: 256 dims, normalised, Titan V2 model id."""
    import io

    sent = {}

    class FakeBedrock:
        def invoke_model(self, **kw):
            sent.update(kw)
            return {"body": io.BytesIO(json.dumps({"embedding": [0.6, 0.8]}).encode())}

    monkeypatch.setattr(embed, "_client", FakeBedrock())
    assert embed.embed("a dragon") == [0.6, 0.8]
    assert sent["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(sent["body"]) == {"inputText": "a dragon", "dimensions": 256, "normalize": True}


def test_indexed_text_includes_name_genres_and_description():
    t = {"title": "Sintel", "genres": ["fantasy", "adventure"], "description": "A lone warrior."}
    assert embed.title_text(t) == "Sintel. Genres: fantasy, adventure. A lone warrior."
    assert embed.keyword_text(t) == "Genres: fantasy, adventure. A lone warrior."


def test_vector_only_baseline_applies_floor_and_relative_cutoff():
    items = [{"id": "a", "title": "A", "vector": [1.0, 0.0]}, {"id": "b", "title": "B", "vector": [0.6, 0.8]},
             {"id": "c", "title": "C", "vector": [0.0, 1.0]}]
    assert [i for _, i in search.rank_vector("zz", items, [1.0, 0.0])] == ["a"]  # b scores 0.6 < 0.75 x best
    assert search.rank_vector("zz", items, [0.1, 0.0]) == []                    # everything under the floor
