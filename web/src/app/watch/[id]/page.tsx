import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import Player from "@/components/Player";
import { apiGet, NotFoundError } from "@/lib/api";
import type { ContinueItem, Title } from "@/lib/types";

type Props = { params: Promise<{ id: string }> };

export const metadata: Metadata = { title: "Watch" };

export default async function Watch({ params }: Props) {
  const { id } = await params;
  const here = `/watch/${id}`;
  let title: Title;
  try {
    title = (await apiGet<{ title: Title }>(`/titles/${encodeURIComponent(id)}`, here)).title;
  } catch (e) {
    if (e instanceof NotFoundError) notFound();
    throw e;
  }
  if (title.status !== "READY") redirect(`/title/${id}`);
  const { items } = await apiGet<{ items: ContinueItem[] }>("/me/continue-watching", here);
  const resume = Math.floor(Number(items.find((i) => i.title.id === id)?.position ?? 0));

  return (
    <article className="watch">
      <Player titleId={id} title={title.title} resume={resume} />
      <div className="watch-meta">
        <h1>{title.title}</h1>
        <p className="hint">
          {title.year} · {resume > 5 ? `Resuming from ${Math.floor(resume / 60)}:${String(resume % 60).padStart(2, "0")}` : "Starting from the beginning"}
        </p>
        {title.credit && <p className="hint">{title.credit} · <a href={title.license_url} target="_blank" rel="noopener noreferrer">{title.license_name}</a></p>}
        <Link className="btn ghost small" href={`/title/${id}`}>Details</Link>
      </div>
    </article>
  );
}
