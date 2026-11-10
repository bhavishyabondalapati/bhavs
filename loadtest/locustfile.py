"""Load test for the bhavs API (run with `make loadtest`; results land in loadtest/results/).

What it does: simulated viewers hit the same endpoints the website calls, in realistic proportions:
browse the catalogue, load their rows, search, and request a stream token. It does NOT post playback events, so the
analytics data and the test account's watch history stay clean.

Auth: signs the test account (E2E_EMAIL / E2E_PASSWORD from .env) in to Cognito ONCE and shares the ID token, so
Cognito's sign-in rate limits are not part of the test. The token lasts an hour, which is longer than any run here.

Cost of a default run (20 users, 2 minutes, ~2,500 requests): API Gateway ~$0.003, Lambda ~$0.001, Bedrock and
DynamoDB fractions of a cent. Well under one cent. The API is throttled at 25 requests/s (burst 50), so pushing
USERS much higher shows 429 "Too Many Requests" responses: that is the throttle protecting the budget, by design.
"""
# Locust must be imported first: it patches the network stack (gevent) before boto3 loads ssl.
from locust import HttpUser, between, events, task  # isort: skip

import os
import random

import boto3
from botocore import UNSIGNED
from botocore.config import Config

TITLES = ["big-buck-bunny", "sintel", "tears-of-steel", "spring", "cosmos-laundromat", "caminandes-llamigos", "hero"]
QUERIES = ["a lonely dragon", "llama", "robots in the future", "funny animals", "space adventure", "winter",
           "shepherd girl and her dog", "strange machine"]
TOKEN = {}


@events.test_start.add_listener
def sign_in(environment, **_):
    """One Cognito sign-in for the whole run (public app client, so no AWS credentials are needed)."""
    client = boto3.client("cognito-idp", region_name="us-east-2", config=Config(signature_version=UNSIGNED))
    res = client.initiate_auth(
        ClientId=os.environ["BHAVS_COGNITO_CLIENT_ID"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": os.environ["E2E_EMAIL"], "PASSWORD": os.environ["E2E_PASSWORD"]},
    )
    TOKEN["id"] = res["AuthenticationResult"]["IdToken"]


class Viewer(HttpUser):
    wait_time = between(0.5, 1.5)  # think time between clicks

    def on_start(self):
        self.client.headers["authorization"] = f"Bearer {TOKEN['id']}"

    @task(5)
    def browse(self):
        self.client.get("/titles")

    @task(3)
    def rows(self):
        self.client.get("/me/recommendations")
        self.client.get("/me/continue-watching")

    @task(2)
    def title_page(self):
        self.client.get(f"/titles/{random.choice(TITLES)}", name="/titles/[id]")

    @task(2)
    def search(self):
        self.client.get("/search", params={"q": random.choice(QUERIES)}, name="/search?q=[query]")

    @task(1)
    def stream_token(self):
        self.client.get(f"/titles/{random.choice(TITLES)}/stream", name="/titles/[id]/stream")
