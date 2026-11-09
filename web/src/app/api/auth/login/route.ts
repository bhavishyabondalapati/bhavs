import { NextResponse } from "next/server";
import { friendlyError, login } from "@/lib/cognito";
import { setSession } from "@/lib/session";

export async function POST(req: Request) {
  const { email, password } = await req.json().catch(() => ({}));
  if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
    return NextResponse.json({ error: "Email and password are required." }, { status: 400 });
  }
  try {
    await setSession(await login(email.trim().toLowerCase(), password));
    return NextResponse.json({ ok: true });
  } catch (e) {
    const { message, code } = friendlyError(e);
    return NextResponse.json({ error: message, code }, { status: code === "UserNotConfirmedException" ? 403 : 401 });
  }
}
