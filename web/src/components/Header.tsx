import Link from "next/link";
import { getSessionUser } from "@/lib/session";
import SignOutButton from "./SignOutButton";

export default async function Header() {
  const user = await getSessionUser();
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="bhavs home">
        bhavs<span>.</span>
      </Link>
      {user ? (
        <>
          <nav className="site-nav" aria-label="Main">
            <Link href="/">Browse</Link>
            {user.isAdmin && <Link href="/admin">Analytics</Link>}
          </nav>
          {/* A plain GET form: works without JavaScript and lands on /search?q=... */}
          <form className="search" role="search" action="/search" method="get">
            <label htmlFor="site-search" className="sr-only">Search films by title or description</label>
            <input id="site-search" name="q" type="search" placeholder="Search: try “a lonely dragon”"
                   minLength={2} maxLength={200} required autoComplete="off" />
            <button type="submit" className="btn small ghost">Search</button>
          </form>
          <div className="user-box">
            <span className="email" title={user.email}>{user.email}</span>
            <SignOutButton />
          </div>
        </>
      ) : (
        <nav className="site-nav" aria-label="Account" style={{ justifyContent: "flex-end" }}>
          <Link href="/login">Sign in</Link>
          <Link href="/signup">Sign up</Link>
        </nav>
      )}
    </header>
  );
}
