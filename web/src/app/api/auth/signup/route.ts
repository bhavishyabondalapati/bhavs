import { NextResponse } from "next/server";
import { friendlyError, signUp } from "@/lib/cognito";
import { clientIp, rateLimit, tooMany } from "@/lib/rate-limit";

export async function POST(req: Request) {
  // Each sign-up makes Cognito send an email, so keep this low: 5 per IP per hour.
  const rl = rateLimit(`signup:${clientIp(req)}`, 5, 60 * 60_000);
  if (!rl.ok) return tooMany(rl.retryAfterSec);
  const { email, password } = await req.json().catch(() => ({}));
  if (typeof email !== "string" || typeof password !== "string" || !email.includes("@") || password.length < 10) {
    return NextResponse.json({ error: "Enter a valid email and a password of at least 10 characters." }, { status: 400 });
  }
  try {
    await signUp(email.trim().toLowerCase(), password);
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: friendlyError(e).message }, { status: 400 });
  }
}
