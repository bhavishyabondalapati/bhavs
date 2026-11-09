// CloudFront Function (viewer-request): only requests carrying a valid, unexpired token get through.
//
//   /t/<exp>-<hmac>/titles/<id>/...   -> token path (the player's playlists use RELATIVE urls, so the
//                                         token prefix is inherited by every playlist and segment)
//   /titles/<id>/poster.jpg           -> public (artwork on the browse page)
//
// hmac = HMAC-SHA256(secret, "<exp>:<id>") as hex. The secret lives in CloudFront KeyValueStore + SSM,
// never in git or Terraform state. After checking, the token prefix is stripped, so every viewer shares
// one cached copy of each segment.
import cf from 'cloudfront';
import crypto from 'crypto';

const kvs = cf.kvs();

function deny(code, text) {
  return { statusCode: code, statusDescription: text, headers: { 'cache-control': { value: 'no-store' } } };
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function handler(event) {
  const req = event.request;
  const uri = req.uri;

  if (/^\/titles\/[\w-]{1,100}\/poster\.jpg$/.test(uri)) return req;

  const m = uri.match(/^\/t\/(\d{10})-([0-9a-f]{64})(\/titles\/([\w-]{1,100})\/.+)$/);
  if (!m) return deny(403, 'Forbidden');

  const exp = m[1], sig = m[2], path = m[3], id = m[4];
  if (parseInt(exp, 10) < Math.floor(Date.now() / 1000)) return deny(403, 'Expired');

  let key;
  try {
    key = await kvs.get('hmac_key');
  } catch (e) {
    return deny(503, 'Unavailable');
  }
  const expected = crypto.createHmac('sha256', key).update(exp + ':' + id).digest('hex');
  if (!safeEqual(expected, sig)) return deny(403, 'Forbidden');

  req.uri = path;
  return req;
}
