import sys
from pathlib import Path

import boto3
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parent))
import seed_titles

ROOT = Path(__file__).resolve().parent.parent


def test_films_yaml_is_complete():
    films = seed_titles.load_films(ROOT / "films.yaml")
    ids = [f["id"] for f in films]
    assert len(ids) == len(set(ids)) >= 8
    for f in films:
        for k in ("title", "year", "genres", "description", "license_name", "license_url", "credit"):
            assert f.get(k), f"{f['id']} missing {k}"


@mock_aws
def test_seed_is_idempotent_and_keeps_status(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    r = boto3.resource("dynamodb")
    t = r.create_table(TableName="titles", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                       AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                       BillingMode="PAY_PER_REQUEST")
    films = seed_titles.load_films(ROOT / "films.yaml")
    seed_titles.seed(t, films)
    t.update_item(Key={"id": films[0]["id"]}, UpdateExpression="SET #s = :r",
                  ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":r": "READY"})
    seed_titles.seed(t, films)
    assert t.get_item(Key={"id": films[0]["id"]})["Item"]["status"] == "READY"
    assert t.scan()["Count"] == len(films)
