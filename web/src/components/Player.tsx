"use client";

import Hls from "hls.js";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { makeEventSender } from "@/lib/useEventSender";

type Stream = { master: string; sprite_vtt: string; expires_at: number };
const HEARTBEAT_MS = 15_000;

export default function Player({ titleId, title, resume = 0 }: { titleId: string; title: string; resume?: number }) {
  const router = useRouter();
  const video = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [levels, setLevels] = useState<{ height: number; bitrate: number }[]>([]);
  const [current, setCurrent] = useState(-1); // level actually playing
  const [selected, setSelected] = useState(-1); // -1 = auto (ABR)
  const [error, setError] = useState("");

  useEffect(() => {
    const maybeEl = video.current;
    if (!maybeEl) return;
    const el: HTMLVideoElement = maybeEl;
    const send = makeEventSender(titleId);
    let hls: Hls | null = null;
    let lastSeekFrom = 0;
    let retried = false;
    let dead = false;

    const snap = () => {
      const lvl = hlsRef.current?.levels[hlsRef.current.currentLevel];
      return {
        position: Math.floor(el.currentTime),
        duration: Number.isFinite(el.duration) ? Math.floor(el.duration) : undefined,
        bitrate_kbps: lvl ? Math.round(lvl.bitrate / 1000) : undefined,
        rendition: lvl ? `${lvl.height}p` : undefined,
      };
    };

    async function getStream(): Promise<Stream> {
      const res = await fetch(`/api/bhavs/titles/${encodeURIComponent(titleId)}/stream`, { cache: "no-store" });
      if (res.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(`/watch/${titleId}`)}`);
        throw new Error("not signed in");
      }
      if (!res.ok) throw new Error("This film is not ready to stream yet.");
      return res.json();
    }

    async function start(startAt: number) {
      try {
        const s = await getStream();
        if (dead) return;
        if (Hls.isSupported()) {
          hls = new Hls({ startPosition: startAt, capLevelToPlayerSize: false, maxBufferLength: 30 });
          hlsRef.current = hls;
          hls.on(Hls.Events.MANIFEST_PARSED, (_e, d) => {
            setLevels(d.levels.map((l) => ({ height: l.height, bitrate: l.bitrate })));
          });
          hls.on(Hls.Events.LEVEL_SWITCHED, (_e, d) => setCurrent(d.level));
          hls.on(Hls.Events.ERROR, async (_e, data) => {
            if (!data.fatal) return;
            // Token expired mid-session (403): fetch a fresh URL once and carry on from where we were.
            if (!retried && data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              retried = true;
              const pos = el.currentTime;
              hls?.destroy();
              await start(pos);
            } else setError("Playback failed. Please reload the page.");
          });
          hls.loadSource(s.master);
          hls.attachMedia(el);
        } else if (el.canPlayType("application/vnd.apple.mpegurl")) {
          el.src = s.master; // Safari plays HLS natively
          el.currentTime = startAt;
        } else setError("This browser cannot play HLS video.");
      } catch (e) {
        if (!dead) setError(e instanceof Error ? e.message : "Could not start playback.");
      }
    }

    const onPlay = () => send({ type: "play", ...snap() });
    const onPause = () => !el.ended && send({ type: "pause", ...snap() });
    const onSeeking = () => (lastSeekFrom = lastSeekFrom || el.currentTime);
    const onSeeked = () => { send({ type: "seek", ...snap() }); lastSeekFrom = 0; };
    const onEnded = () => send({ type: "complete", ...snap() });
    const onHide = () => { if (!el.paused && !el.ended) send({ type: "pause", ...snap() }, { beacon: true }); };

    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("seeking", onSeeking);
    el.addEventListener("seeked", onSeeked);
    el.addEventListener("ended", onEnded);
    window.addEventListener("pagehide", onHide);
    const heartbeat = setInterval(() => { if (!el.paused && !el.ended) send({ type: "heartbeat", ...snap() }); }, HEARTBEAT_MS);

    void start(resume);
    return () => {
      dead = true;
      clearInterval(heartbeat);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("seeking", onSeeking);
      el.removeEventListener("seeked", onSeeked);
      el.removeEventListener("ended", onEnded);
      window.removeEventListener("pagehide", onHide);
      if (!el.paused && !el.ended) send({ type: "pause", ...snap() }, { beacon: true });
      hls?.destroy();
      hlsRef.current = null;
    };
  }, [titleId, resume, router]);

  function choose(level: number) {
    setSelected(level);
    if (hlsRef.current) hlsRef.current.currentLevel = level; // -1 re-enables ABR
  }

  const label = (i: number) => (levels[i] ? `${levels[i].height}p` : "…");
  return (
    <div className="player">
      <video ref={video} controls playsInline aria-label={`Video player: ${title}`} data-testid="video" />
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="player-bar">
        <label htmlFor="quality">Quality</label>
        <select id="quality" value={selected} onChange={(e) => choose(Number(e.target.value))} disabled={levels.length === 0}>
          <option value={-1}>Auto</option>
          {levels.map((l, i) => <option key={i} value={i}>{l.height}p</option>).reverse()}
        </select>
        <span className="hint" aria-live="polite" data-testid="now-playing">
          {current >= 0 ? `Playing ${label(current)}${selected === -1 ? " (auto)" : ""}` : "Loading…"}
        </span>
      </div>
    </div>
  );
}
