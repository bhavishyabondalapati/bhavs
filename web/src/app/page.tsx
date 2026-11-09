import Link from "next/link";
import Row from "@/components/Row";
import TitleCard from "@/components/TitleCard";
import { apiGet } from "@/lib/api";
import type { ContinueItem, RecRow, Title } from "@/lib/types";

export default async function Browse() {
  const [{ titles }, { items }, { rows }] = await Promise.all([
    apiGet<{ titles: Title[] }>("/titles", "/"),
    apiGet<{ items: ContinueItem[] }>("/me/continue-watching", "/"),
    apiGet<{ rows: RecRow[] }>("/me/recommendations", "/"),
  ]);

  if (titles.length === 0) return <p className="empty">The catalogue is empty. Run the ingest to add films.</p>;

  const featured = titles.find((t) => t.status === "READY") ?? titles[0];
  const byGenre = new Map<string, Title[]>();
  for (const t of titles) for (const g of t.genres ?? []) byGenre.set(g, [...(byGenre.get(g) ?? []), t]);
  const genreRows = [...byGenre.entries()].filter(([, v]) => v.length >= 2).sort((a, b) => b[1].length - a[1].length);

  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <span className="eyebrow">Featured</span>
        <h1 id="hero-title">{featured.title}</h1>
        <p>{featured.description}</p>
        <div className="actions">
          <Link className="btn" href={`/title/${featured.id}`}>View details</Link>
        </div>
      </section>

      {items.length > 0 && (
        <Row label="Continue watching">
          {items.map((i) => (
            <TitleCard key={i.title.id} title={i.title}
                       progress={i.duration ? Math.min(1, i.position / i.duration) : undefined} />
          ))}
        </Row>
      )}
      {rows.map((r) => (
        <Row key={r.key} label={r.label}>{r.titles.map((t) => <TitleCard key={t.id} title={t} />)}</Row>
      ))}
      <Row label="All films">{titles.map((t) => <TitleCard key={t.id} title={t} />)}</Row>
      {genreRows.map(([g, list]) => (
        <Row key={g} label={g[0].toUpperCase() + g.slice(1)}>{list.map((t) => <TitleCard key={t.id} title={t} />)}</Row>
      ))}
    </>
  );
}
