import Link from "next/link";
import type { Title } from "@/lib/types";
import Poster from "./Poster";

export default function TitleCard({ title, progress }: { title: Title; progress?: number }) {
  const ready = title.status === "READY";
  return (
    <Link href={`/title/${title.id}`} className="card">
      <Poster title={title} />
      <div className="card-meta">
        <div className="card-title">{title.title}</div>
        <div className="card-sub">
          {title.year}
          {!ready && <> · <span className="badge">Coming soon</span></>}
        </div>
        {progress !== undefined && (
          <div className="progress" role="progressbar" aria-label={`Watched ${Math.round(progress * 100)}%`}
               aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
            <span style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        )}
      </div>
    </Link>
  );
}
