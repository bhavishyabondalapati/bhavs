"use client";

export type PlayerEvent = {
  type: "play" | "pause" | "seek" | "heartbeat" | "complete";
  position: number;
  duration?: number;
  bitrate_kbps?: number;
  rendition?: string;
};

/** Sends player events to the bhavs API through the same-origin proxy (the auth cookie is httpOnly). */
export function makeEventSender(titleId: string) {
  const sessionId =
    typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
  return function send(e: PlayerEvent, opts: { beacon?: boolean } = {}) {
    const body = JSON.stringify({ ...e, title_id: titleId, session_id: sessionId, ts: Date.now() });
    try {
      if (opts.beacon && navigator.sendBeacon) {
        // Survives the page closing; Blob keeps the content type JSON.
        navigator.sendBeacon("/api/bhavs/events", new Blob([body], { type: "application/json" }));
        return;
      }
      void fetch("/api/bhavs/events", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true });
    } catch {
      /* analytics must never break playback */
    }
  };
}
