"use client";

import { useId, useRef, type ReactNode } from "react";

/** A titled horizontal shelf. Cards are links, so Tab moves through them and scrolls the row. */
export default function Row({ label, children }: { label: string; children: ReactNode[] }) {
  const id = useId();
  const list = useRef<HTMLUListElement>(null);
  const scroll = (dir: 1 | -1) => {
    const el = list.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: reduce ? "auto" : "smooth" });
  };
  return (
    <section className="row" aria-labelledby={id}>
      <div className="row-head">
        <h2 id={id}>{label}</h2>
        <div className="row-ctl">
          <button type="button" onClick={() => scroll(-1)} aria-label={`Scroll ${label} left`}>‹</button>
          <button type="button" onClick={() => scroll(1)} aria-label={`Scroll ${label} right`}>›</button>
        </div>
      </div>
      <ul className="row-list" ref={list}>
        {children.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}
