-- Average share of the film watched per session (furthest position reached / duration).
-- One parameter (the dt placeholder): first day to include, e.g. '2026-11-01' (the admin report uses the last 30 days). The dt filter also
-- stops Athena checking every possible hour folder since the projection start (that cost real money: see COSTS.md).
WITH sessions AS (
  SELECT title_id, session_id, max(position) AS furthest, max(duration) AS duration
  FROM events
  WHERE dt >= ?
  GROUP BY title_id, session_id
)
SELECT title_id,
       round(avg(least(furthest / duration, 1.0)) * 100, 1) AS avg_watch_pct,
       count(*) AS sessions
FROM sessions
WHERE duration > 0
GROUP BY title_id
ORDER BY avg_watch_pct DESC
