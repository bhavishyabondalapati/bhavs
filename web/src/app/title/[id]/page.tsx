import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import Poster from "@/components/Poster";
import { apiGet, NotFoundError } from "@/lib/api";
import type { Title } from "@/lib/types";

type Props = { params: Promise<{ id: string }> };

async function load(id: string) {
  try {
    return (await apiGet<{ title: Title }>(`/titles/${encodeURIComponent(id)}`, `/title/${id}`)).title;
  } catch (e) {
    if (e instanceof NotFoundError) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  return { title: (await load(id)).title };
}

export default async function TitlePage({ params }: Props) {
  const t = await load((await params).id);
  const ready = t.status === "READY";
  const minutes = t.duration_sec ? Math.round(t.duration_sec / 60) : null;
  return (
    <article className="detail">
      <Poster title={t} />
      <div>
        <h1>{t.title}</h1>
        <div className="meta">
          <span>{t.year}</span>
          {minutes && <span>· {minutes} min</span>}
          {t.genres?.map((g) => <span key={g} className="badge">{g}</span>)}
        </div>
        {!ready && <p className="notice" role="status">This film is still being prepared for streaming.</p>}
        <p className="desc">{t.description}</p>
        {ready ? (
          <Link className="btn" href={`/watch/${t.id}`}>Play</Link>
        ) : (
          <button className="btn" type="button" aria-disabled="true" disabled>Coming soon</button>
        )}
        {(t.credit || t.license_name) && (
          <aside className="license" aria-label="License and credit">
            <strong>Credit:</strong> {t.credit}
            <br />
            <strong>License:</strong>{" "}
            {t.license_url ? <a href={t.license_url} target="_blank" rel="noopener noreferrer">{t.license_name}</a> : t.license_name}
          </aside>
        )}
      </div>
    </article>
  );
}
