import { NextRequest, NextResponse } from "next/server";
import { refresh } from "@/lib/cognito";
import { getRefreshToken, setSession } from "@/lib/session";

// Only same-site relative paths, so this can't be used as an open redirect.
function safeNext(raw: string | null) {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.includes("\\") ? raw : "/";
}

export async function GET(req: NextRequest) {
  const next = safeNext(req.nextUrl.searchParams.get("next"));
  const rt = await getRefreshToken();
  if (rt) {
    try {
      await setSession(await refresh(rt));
      return NextResponse.redirect(new URL(next, req.url));
    } catch {
      /* fall through to login */
    }
  }
  const to = new URL("/login", req.url);
  to.searchParams.set("next", next);
  const res = NextResponse.redirect(to);
  for (const n of ["bhavs_id", "bhavs_access", "bhavs_refresh"]) res.cookies.delete(n);
  return res;
}
