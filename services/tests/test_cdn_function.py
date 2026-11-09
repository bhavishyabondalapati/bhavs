"""The CloudFront Function (JS) and the Lambda that mints tokens (Python) must agree. Runs the real JS in node."""
import hashlib
import hmac
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "infra/persistent/cdn/viewer_request.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")

HARNESS = r"""
const fs = require('fs'); const crypto = require('crypto');
let src = fs.readFileSync(process.argv[1], 'utf8')
  .replace(/^import .*$/gm, '');
const kvs = { get: async () => process.argv[2] };
const cf = { kvs: () => kvs };
const fn = new Function('cf', 'crypto', src + '\nreturn handler;')(cf, crypto);
fn({ request: { uri: process.argv[3] } }).then(r => console.log(JSON.stringify(r)));
"""


def run(uri, key="k" * 64):
    out = subprocess.run(["node", "-e", HARNESS, str(JS), key, uri], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def token(title_id, exp, key="k" * 64):
    return f"{exp}-" + hmac.new(key.encode(), f"{exp}:{title_id}".encode(), hashlib.sha256).hexdigest()


def test_valid_token_is_stripped():
    exp = int(time.time()) + 600
    r = run(f"/t/{token('sintel', exp)}/titles/sintel/720p/seg_0001.ts")
    assert r["uri"] == "/titles/sintel/720p/seg_0001.ts"


def test_poster_is_public():
    assert run("/titles/sintel/poster.jpg")["uri"] == "/titles/sintel/poster.jpg"


@pytest.mark.parametrize("uri", [
    "/titles/sintel/master.m3u8",                       # no token
    "/t/short/titles/sintel/master.m3u8",               # malformed token
])
def test_missing_or_malformed_denied(uri):
    assert run(uri)["statusCode"] == 403


def test_expired_denied():
    exp = int(time.time()) - 5
    assert run(f"/t/{token('sintel', exp)}/titles/sintel/master.m3u8")["statusCode"] == 403


def test_token_for_other_title_denied():
    exp = int(time.time()) + 600
    assert run(f"/t/{token('sintel', exp)}/titles/spring/master.m3u8")["statusCode"] == 403


def test_wrong_key_denied():
    exp = int(time.time()) + 600
    assert run(f"/t/{token('sintel', exp, key='x' * 64)}/titles/sintel/master.m3u8")["statusCode"] == 403
