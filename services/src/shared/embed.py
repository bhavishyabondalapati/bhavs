"""Text embeddings with Amazon Bedrock (Titan Text Embeddings V2) plus the tiny bit of vector maths search needs.

An *embedding* turns text into a list of numbers so that texts with similar MEANING end up close together. Titan V2 can
return 256, 512 or 1024 numbers; we use 256 (plenty for a small catalogue, and the cheapest to store). We ask Titan to
normalise each vector to length 1, so cosine similarity is just a dot product.
"""
import json
import os

import boto3

MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = 256

_client = None


def bedrock():
    """Lazily created Bedrock runtime client (lazy so tests can swap it)."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-2"))
    return _client


def embed(text):
    """One text -> one normalised vector (list of floats)."""
    body = json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True})
    res = bedrock().invoke_model(modelId=MODEL_ID, body=body, contentType="application/json", accept="application/json")
    return json.loads(res["body"].read())["embedding"]


def title_text(t):
    """What we embed for a title: its name, genres and description (so 'a lonely dragon' can find Sintel)."""
    genres = ", ".join(t.get("genres", []))
    return f"{t.get('title', '')}. Genres: {genres}. {t.get('description', '')}".strip()


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))
