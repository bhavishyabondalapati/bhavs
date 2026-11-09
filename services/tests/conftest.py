import boto3
import pytest
from moto import mock_aws
from shared import common


@pytest.fixture
def db(monkeypatch):
    """Fake DynamoDB with the four bhavs tables."""
    for k, v in {"TITLES_TABLE": "titles", "USERS_TABLE": "users",
                 "HISTORY_TABLE": "history", "RECS_TABLE": "recs",
                 "AWS_DEFAULT_REGION": "us-east-2", "AWS_ACCESS_KEY_ID": "x",
                 "AWS_SECRET_ACCESS_KEY": "x"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        common._resource = None
        r = boto3.resource("dynamodb")
        def mk(name, hash_key, range_key=None):
            keys = [{"AttributeName": hash_key, "KeyType": "HASH"}]
            attrs = [{"AttributeName": hash_key, "AttributeType": "S"}]
            if range_key:
                keys.append({"AttributeName": range_key, "KeyType": "RANGE"})
                attrs.append({"AttributeName": range_key, "AttributeType": "S"})
            r.create_table(TableName=name, KeySchema=keys, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")
        mk("titles", "id"); mk("users", "user_id"); mk("history", "user_id", "title_id"); mk("recs", "user_id", "row_key")
        titles = r.Table("titles")
        titles.put_item(Item={"id": "sintel", "title": "Sintel", "year": 2010, "status": "READY", "genres": ["fantasy"], "secret_internal": "x"})
        titles.put_item(Item={"id": "bbb", "title": "Big Buck Bunny", "year": 2008, "status": "READY", "genres": ["comedy"]})
        titles.put_item(Item={"id": "broken", "title": "Broken", "year": 2020, "status": "FAILED"})
        yield r
    common._resource = None


def api_event(uid="u1", body=None, path=None, groups=""):
    import json
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": uid, "email": "a@b.c", "cognito:groups": groups}}}},
        "pathParameters": path or {},
        "body": json.dumps(body) if body is not None else None,
    }
