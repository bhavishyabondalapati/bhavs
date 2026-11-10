-- How many viewing sessions started per title, and by how many different people.
-- One parameter (the dt placeholder): first day to include, e.g. '2026-11-01' (the admin report uses the last 30 days). The dt filter also
-- stops Athena checking every possible hour folder since the projection start (that cost real money: see COSTS.md).
SELECT title_id,
       count(DISTINCT session_id) AS views,
       count(DISTINCT user_id)    AS unique_viewers
FROM events
WHERE dt >= ? AND type = 'play'
GROUP BY title_id
ORDER BY views DESC
