/**
 * Small in-memory sliding-window rate limiter for the auth routes (login, sign-up, confirm).
 *
 * It lives in the memory of one server instance, so on Vercel each warm instance counts on its own:
 * it slows down a script hammering the endpoint, it is not a strict global limit. Cognito applies its
 * own lockouts and request quotas behind it. For a strict limit, swap the Map for a shared store
 * (Redis / Upstash / DynamoDB) behind the same function.
 */
const hits = new Map<string, number[]>();

export function rateLimit(key: string, limit: number, windowMs: number, now = Date.now()): { ok: boolean; retryAfterSec: number } {
  const recent = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
  if (recent.length >= limit) {
    hits.set(key, recent);
    return { ok: false, retryAfterSec: Math.max(1, Math.ceil((windowMs - (now - recent[0]!)) / 1000)) };
  }
  recent.push(now);
  hits.set(key, recent);
  // Keep the map small: drop keys with no recent hits once it grows.
  if (hits.size > 5000) for (const [k, v] of hits) if (!v.some((t) => now - t < windowMs)) hits.delete(k);
  return { ok: true, retryAfterSec: 0 };
}

/** Client IP as reported by the platform (Vercel sets x-forwarded-for). */
export function clientIp(req: Request): string {
  const xff = req.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0]!.trim();
  return req.headers.get("x-real-ip") ?? "unknown";
}

export function tooMany(retryAfterSec: number) {
  return Response.json(
    { error: "Too many attempts. Wait a few minutes and try again." },
    { status: 429, headers: { "Retry-After": String(retryAfterSec) } },
  );
}
