import { NextResponse } from "next/server";
import { friendlyError, login } from "@/lib/cognito";
import { clientIp, rateLimit, tooMany } from "@/lib/rate-limit";
import { setSession } from "@/lib/session";

export async function POST(req: Request) {
  // 20 attempts per IP and 10 per email in 15 minutes (see lib/rate-limit.ts for what this does and does not stop).
  const byIp = rateLimit(`login:ip:${clientIp(req)}`, 20, 15 * 60_000);
  if (!byIp.ok) return tooMany(byIp.retryAfterSec);
  const { email, password } = await req.json().catch(() => ({}));
  if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
    return NextResponse.json({ error: "Email and password are required." }, { status: 400 });
  }
  const byEmail = rateLimit(`login:email:${email.trim().toLowerCase()}`, 10, 15 * 60_000);
  if (!byEmail.ok) return tooMany(byEmail.retryAfterSec);
  try {
    await setSession(await login(email.trim().toLowerCase(), password));
    return NextResponse.json({ ok: true });
  } catch (e) {
    const { message, code } = friendlyError(e);
    const unconfirmed = code === "UserNotConfirmedException";
    // Only this one code is sent on (the form uses it to show the confirm step); other exception names stay server-side.
    return NextResponse.json({ error: message, ...(unconfirmed ? { code } : {}) }, { status: unconfirmed ? 403 : 401 });
  }
}
