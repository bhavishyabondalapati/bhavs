import type { Metadata } from "next";
import TitleCard from "@/components/TitleCard";
import { apiGet } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

type Props = { searchParams: Promise<{ q?: string | string[] }> };

export const metadata: Metadata = { title: "Search" };

/** Semantic search results. The API embeds the query with Bedrock and ranks titles by meaning, not just keywords. */
export default async function SearchPage({ searchParams }: Props) {
  const raw = (await searchParams).q;
  const q = (Array.isArray(raw) ? raw[0] : raw ?? "").trim().slice(0, 200);

  if (q.length < 2) {
    return (
      <section className="results">
        <h1>Search</h1>
        <p className="hint">Type at least two characters. You can describe a film, for example “a lonely dragon”.</p>
      </section>
    );
  }

  const path = `/search?q=${encodeURIComponent(q)}`;
  const { results } = await apiGet<{ results: SearchResult[] }>(path, path);

  return (
    <section className="results" aria-labelledby="results-title">
      <h1 id="results-title">Results for “{q}”</h1>
      <p className="hint" role="status">
        {results.length === 0
          ? "Nothing in the catalogue matches that. Try describing the story or a genre."
          : `${results.length} ${results.length === 1 ? "film" : "films"}, best match first.`}
      </p>
      {results.length > 0 && (
        <ul className="results-grid">
          {results.map((t) => (
            <li key={t.id}><TitleCard title={t} /></li>
          ))}
        </ul>
      )}
    </section>
  );
}
