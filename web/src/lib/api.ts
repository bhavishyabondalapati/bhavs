import { redirect } from "next/navigation";
import { getIdToken } from "./session";

/**
 * Server-side call to the bhavs API with the user's ID token.
 * No token -> /login. 401 -> bounce through /api/session/refresh, then back to `returnTo`.
 */
export async function apiGet<T>(path: string, returnTo: string): Promise<T> {
  const token = await getIdToken();
  if (!token) redirect(`/api/session/refresh?next=${encodeURIComponent(returnTo)}`);
  const res = await fetch(`${process.env.BHAVS_API_URL}${path}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401) redirect(`/api/session/refresh?next=${encodeURIComponent(returnTo)}`);
  if (res.status === 404) throw new NotFoundError();
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export class NotFoundError extends Error {}
