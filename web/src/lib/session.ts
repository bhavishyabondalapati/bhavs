import { cookies } from "next/headers";
import type { Tokens } from "./cognito";

export const ID_COOKIE = "bhavs_id";
export const ACCESS_COOKIE = "bhavs_access";
export const REFRESH_COOKIE = "bhavs_refresh";

const base = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

/** Tokens live in httpOnly cookies so page scripts (and any XSS) can never read them. */
export async function setSession(t: Tokens) {
  const jar = await cookies();
  jar.set(ID_COOKIE, t.idToken, { ...base, maxAge: t.expiresIn });
  jar.set(ACCESS_COOKIE, t.accessToken, { ...base, maxAge: t.expiresIn });
  if (t.refreshToken) jar.set(REFRESH_COOKIE, t.refreshToken, { ...base, maxAge: 60 * 60 * 24 * 30 });
}

export async function clearSession() {
  const jar = await cookies();
  for (const n of [ID_COOKIE, ACCESS_COOKIE, REFRESH_COOKIE]) jar.delete(n);
}

export async function getIdToken() {
  return (await cookies()).get(ID_COOKIE)?.value;
}

export async function getRefreshToken() {
  return (await cookies()).get(REFRESH_COOKIE)?.value;
}

export type SessionUser = { email: string; isAdmin: boolean };

/** Reads display info from the ID token. NOT a security check: the API verifies the signature. */
export async function getSessionUser(): Promise<SessionUser | null> {
  const token = await getIdToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());
    const groups: string[] = payload["cognito:groups"] ?? [];
    return { email: payload.email ?? "", isAdmin: groups.includes("admin") };
  } catch {
    return null;
  }
}
