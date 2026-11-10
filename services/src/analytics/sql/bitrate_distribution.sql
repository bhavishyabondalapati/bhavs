-- Which renditions viewers actually watched (one heartbeat is sent every 15 s of playback).
-- One parameter (the dt placeholder): first day to include, e.g. '2026-11-01' (the admin report uses the last 30 days). The dt filter also
-- stops Athena checking every possible hour folder since the projection start (that cost real money: see COSTS.md).
SELECT rendition,
       round(avg(bitrate_kbps))                                AS avg_bitrate_kbps,
       count(*)                                                AS heartbeats,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)       AS share_pct
FROM events
WHERE dt >= ? AND type = 'heartbeat' AND rendition IS NOT NULL
GROUP BY rendition
ORDER BY CAST(regexp_extract(rendition, '\d+') AS integer)
