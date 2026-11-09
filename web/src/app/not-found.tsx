import Link from "next/link";

export default function NotFound() {
  return (
    <p className="empty">
      We couldn&apos;t find that page. <Link href="/" style={{ color: "var(--accent)" }}>Back to browse</Link>
    </p>
  );
}
