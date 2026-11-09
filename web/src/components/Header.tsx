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
          </nav>
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
