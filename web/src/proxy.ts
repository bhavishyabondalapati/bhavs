import { NextResponse, type NextRequest } from "next/server";

/**
 * Content Security Policy with a fresh nonce per request (Next.js puts the nonce on its own <script> tags).
 *
 * What the policy allows, and why:
 * - scripts: only this site's scripts carrying today's nonce ('strict-dynamic' lets them load their own chunks).
 * - styles: 'unsafe-inline' because React renders a few `style="width: 42%"` attributes (progress bars, posters);
 *   nonces cannot cover style attributes. Scripts are the real XSS risk and those stay strict.
 * - images / media / connect: the CloudFront CDN (posters, HLS playlists and segments) plus blob:, which is how
 *   hls.js feeds video into the <video> element (Media Source Extensions).
 * - worker: blob:, because hls.js runs its demuxer in a Web Worker created from a blob URL.
 * - frames: none (no one may embed bhavs in an iframe: stops clickjacking).
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const cdn = process.env.BHAVS_CDN_URL ?? "";
  const dev = process.env.NODE_ENV === "development";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${cdn}`,
    `media-src 'self' blob: ${cdn}`,
    `connect-src 'self' ${cdn}`,
    "worker-src 'self' blob:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(dev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: API routes return JSON, static files need no nonce. Prefetches are skipped (no HTML rendered).
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
