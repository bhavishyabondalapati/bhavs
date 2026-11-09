import { NextResponse } from "next/server";
import { confirmSignUp, friendlyError } from "@/lib/cognito";

export async function POST(req: Request) {
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
