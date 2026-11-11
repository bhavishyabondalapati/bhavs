import { NextResponse } from "next/server";
import { confirmSignUp, friendlyError } from "@/lib/cognito";
import { clientIp, rateLimit, tooMany } from "@/lib/rate-limit";

export async function POST(req: Request) {
  // 10 code attempts per IP in 10 minutes (a 6-digit code must not be guessable by brute force).
  const rl = rateLimit(`confirm:${clientIp(req)}`, 10, 10 * 60_000);
  if (!rl.ok) return tooMany(rl.retryAfterSec);
  const { email, code } = await req.json().catch(() => ({}));
  if (typeof email !== "string" || typeof code !== "string" || !/^\d{6}$/.test(code.trim())) {
    return NextResponse.json({ error: "Enter the 6-digit code from your email." }, { status: 400 });
  }
  try {
    await confirmSignUp(email.trim().toLowerCase(), code.trim());
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: friendlyError(e).message }, { status: 400 });
  }
}
