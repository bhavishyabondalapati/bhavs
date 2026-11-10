-- Where people stop watching: for sessions that did not finish, the decile (0,10,...,90 %) of the last position.
-- One parameter (the dt placeholder): first day to include, e.g. '2026-11-01' (the admin report uses the last 30 days). The dt filter also
-- stops Athena checking every possible hour folder since the projection start (that cost real money: see COSTS.md).
WITH last_event AS (
  SELECT title_id, session_id,
         max_by(position, ts)      AS last_position,
         max(duration)             AS duration,
         bool_or(type = 'complete') AS finished
  FROM events
  WHERE dt >= ?
  GROUP BY title_id, session_id
)
SELECT title_id,
       CAST(least(floor(last_position / duration * 10), 9) AS integer) * 10 AS dropped_at_pct,
       count(*) AS sessions
FROM last_event
WHERE NOT finished AND duration > 0
GROUP BY 1, 2
ORDER BY 1, 2
