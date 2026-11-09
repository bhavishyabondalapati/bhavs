import { NextResponse } from "next/server";
import { friendlyError, signUp } from "@/lib/cognito";

export async function POST(req: Request) {
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
