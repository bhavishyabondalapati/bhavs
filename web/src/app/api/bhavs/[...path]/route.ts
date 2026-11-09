import { NextRequest, NextResponse } from "next/server";
import { getIdToken } from "@/lib/session";

// Browser code talks to this proxy, never to the API directly: the token stays in an httpOnly cookie.
// Only these API paths may be reached (keeps the proxy from becoming an open relay).
const ALLOWED = [
  /^titles$/, /^titles\/[\w-]{1,100}$/, /^titles\/[\w-]{1,100}\/stream$/, /^me$/, /^me\/continue-watching$/,
  /^me\/recommendations$/, /^events$/, /^search$/, /^admin\/analytics$/,
];

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.some((r) => r.test(joined))) return NextResponse.json({ error: "not found" }, { status: 404 });
  const token = await getIdToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });

  const url = `${process.env.BHAVS_API_URL}/${joined}${req.nextUrl.search}`;
  const body = req.method === "POST" ? await req.text() : undefined;
  if (body && body.length > 8_000) return NextResponse.json({ error: "too large" }, { status: 413 });
  const res = await fetch(url, {
    method: req.method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body,
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
