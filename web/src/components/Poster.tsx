import type { Title } from "@/lib/types";

// Deterministic gradient per title, so cards look distinct before real posters exist.
function hue(id: string) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

// Posters are public artwork served by CloudFront (the stream itself needs a token, the poster does not).
function posterUrl(t: Title) {
  const cdn = process.env.BHAVS_CDN_URL;
  return cdn && t.poster_path ? `${cdn}/${t.poster_path}` : undefined;
}

export default function Poster({ title, src = posterUrl(title) }: { title: Title; src?: string }) {
  const h = hue(title.id);
  const bg = `linear-gradient(160deg, hsl(${h} 55% 28%), hsl(${(h + 50) % 360} 60% 14%))`;
  return (
    <div className="poster" style={{ background: bg }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- posters are served by CloudFront; no optimizer needed */}
      {src ? <img src={src} alt={`Poster for ${title.title}`} loading="lazy" /> : null}
      {/* Decorative art title: the link/heading next to it already names the film. */}
      {!src && (
        <span className="art-title" aria-hidden="true">
          {title.title}
        </span>
      )}
    </div>
  );
}
