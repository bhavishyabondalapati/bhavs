import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { apiGet } from "@/lib/api";
import { getSessionUser } from "@/lib/session";
import type { Title } from "@/lib/types";

export const metadata: Metadata = { title: "Analytics" };

type Report = {
  generated_at: number | null;
  since?: string;
  days?: number;
  empty?: boolean;
  totals?: { events: number; users: number; sessions: number; synthetic_events: number };
  views_per_title?: { title_id: string; views: number; unique_viewers: number }[];
  avg_watch_pct?: { title_id: string; avg_watch_pct: number; sessions: number }[];
  drop_off?: { title_id: string; dropped_at_pct: number; sessions: number }[];
  bitrate_distribution?: { rendition: string; avg_bitrate_kbps: number; heartbeats: number; share_pct: number }[];
};

const nf = new Intl.NumberFormat("en-US");

function Bar({ value, max }: { value: number; max: number }) {
  return (
    <span className="bar" aria-hidden="true">
      <span style={{ width: `${max ? Math.max(2, (value / max) * 100) : 0}%` }} />
    </span>
  );
}

export default async function Admin() {
  const user = await getSessionUser();
  if (!user?.isAdmin) notFound(); // hide the page's existence; the API enforces the group too

  const [report, { titles }] = await Promise.all([
    apiGet<Report>("/admin/analytics", "/admin"),
    apiGet<{ titles: Title[] }>("/titles", "/admin"),
  ]);
  const name = (id: string) => titles.find((t) => t.id === id)?.title ?? id;

  if (report.empty || !report.totals) {
    return (
      <section className="admin">
        <h1>Analytics</h1>
        <p className="notice">No report yet. Events are compacted hourly; run <code>make analytics-refresh</code> to build one now.</p>
      </section>
    );
  }

  const t = report.totals;
  const synthPct = t.events ? Math.round((t.synthetic_events / t.events) * 100) : 0;
  const views = report.views_per_title ?? [];
  const maxViews = Math.max(1, ...views.map((v) => v.views));
  const dropByTitle = new Map<string, Map<number, number>>();
  for (const d of report.drop_off ?? []) {
    const m = dropByTitle.get(d.title_id) ?? new Map();
    m.set(d.dropped_at_pct, d.sessions);
    dropByTitle.set(d.title_id, m);
  }
  const maxDrop = Math.max(1, ...(report.drop_off ?? []).map((d) => d.sessions));

  return (
    <section className="admin">
      <h1>Analytics</h1>
      {synthPct > 0 && (
        <p className="notice" role="note">
          {synthPct}% of these events are <strong>synthetic</strong> (simulated viewers, used to demo analytics and recommendations).
        </p>
      )}
      <p className="hint">
        {report.since ? <>Last {report.days} days (since {report.since}) · </> : null}
        Updated {report.generated_at ? new Date(report.generated_at * 1000).toLocaleString() : "never"} · built by Athena
        over Parquet in S3
      </p>

      <ul className="stats" aria-label="Totals">
        <li><strong>{nf.format(t.events)}</strong> events</li>
        <li><strong>{nf.format(t.sessions)}</strong> sessions</li>
        <li><strong>{nf.format(t.users)}</strong> viewers</li>
      </ul>

      <h2>Views per title</h2>
      <table className="data">
        <thead><tr><th>Title</th><th>Views</th><th>Unique viewers</th><th><span className="sr-only">Chart</span></th></tr></thead>
        <tbody>
          {views.map((v) => (
            <tr key={v.title_id}><td>{name(v.title_id)}</td><td>{nf.format(v.views)}</td><td>{nf.format(v.unique_viewers)}</td><td><Bar value={v.views} max={maxViews} /></td></tr>
          ))}
        </tbody>
      </table>

      <h2>Average watch %</h2>
      <table className="data">
        <thead><tr><th>Title</th><th>Avg watched</th><th>Sessions</th><th><span className="sr-only">Chart</span></th></tr></thead>
        <tbody>
          {(report.avg_watch_pct ?? []).map((v) => (
            <tr key={v.title_id}><td>{name(v.title_id)}</td><td>{v.avg_watch_pct}%</td><td>{nf.format(v.sessions)}</td><td><Bar value={v.avg_watch_pct} max={100} /></td></tr>
          ))}
        </tbody>
      </table>

      <h2>Where viewers drop off</h2>
      <p className="hint">Sessions that stopped before the end, by how far in they were (each column is a tenth of the film). Darker = more people stopped there.</p>
      <table className="data heat">
        <thead>
          <tr><th>Title</th>{Array.from({ length: 10 }, (_, i) => <th key={i}>{i * 10}%</th>)}</tr>
        </thead>
        <tbody>
          {[...dropByTitle.entries()].map(([id, m]) => (
            <tr key={id}>
              <td>{name(id)}</td>
              {Array.from({ length: 10 }, (_, i) => {
                const n = m.get(i * 10) ?? 0;
                return (
                  <td key={i} style={{ background: `color-mix(in srgb, var(--accent) ${Math.round((n / maxDrop) * 85)}%, transparent)` }}>
                    {n || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Bitrate distribution</h2>
      <table className="data">
        <thead><tr><th>Rendition</th><th>Avg bitrate</th><th>Share of playback</th><th><span className="sr-only">Chart</span></th></tr></thead>
        <tbody>
          {(report.bitrate_distribution ?? []).map((b) => (
            <tr key={b.rendition}><td>{b.rendition}</td><td>{nf.format(b.avg_bitrate_kbps)} kbit/s</td><td>{b.share_pct}%</td><td><Bar value={b.share_pct} max={100} /></td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
