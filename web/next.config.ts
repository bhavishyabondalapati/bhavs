import type { NextConfig } from "next";

// Security headers sent with every response (the per-request Content-Security-Policy is set in src/proxy.ts).
const securityHeaders = [
  // Browsers must use HTTPS for this site for 2 years (Vercel serves HTTPS only).
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  // Do not guess content types (stops a text file being run as a script).
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Old-browser fallback for CSP frame-ancestors 'none': never show bhavs inside someone else's frame.
  { key: "X-Frame-Options", value: "DENY" },
  // Send only our origin (never full URLs with ids) to other sites.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Turn off powerful browser features the app never uses; fullscreen stays allowed for the player.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), fullscreen=(self)" },
  // Isolate our window from pages we open (and that open us).
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
