"""Load films.yaml metadata into the titles table. Safe to re-run (never downgrades status)."""
import os
from pathlib import Path

import boto3
import yaml

FIELDS = ("title", "year", "genres", "duration_sec", "description", "license_name", "license_url", "credit")


def load_films(path):
    return yaml.safe_load(Path(path).read_text())["films"]


def to_item(film):
    item = {"id": film["id"]}
    item.update({k: film[k] for k in FIELDS if k in film})
    return item


def seed(table, films):
    for f in films:
        item = to_item(f)
        fields = [k for k in item if k != "id"]
        sets = ", ".join(f"#{k} = :{k}" for k in fields)
        names = {f"#{k}": k for k in fields}
        names["#status"] = "status"
        vals = {f":{k}": item[k] for k in fields}
        vals[":pending"] = "PENDING"
        # `status` is set once and never overwritten by a re-seed.
        table.update_item(
            Key={"id": item["id"]},
            UpdateExpression=f"SET {sets}, #status = if_not_exists(#status, :pending)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )
    return len(films)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    name = os.environ.get("TITLES_TABLE", "bhavs-titles")
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    table = session.resource("dynamodb").Table(name)
    print(f"seeded {seed(table, load_films(root / 'films.yaml'))} titles into {name}")
