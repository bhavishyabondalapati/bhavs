-- One parameter (the dt placeholder): first day to include, e.g. '2026-11-01' (the admin report uses the last 30 days). The dt filter also
-- stops Athena checking every possible hour folder since the projection start (that cost real money: see COSTS.md).
SELECT count(*)                       AS events,
       count(DISTINCT user_id)        AS users,
       count(DISTINCT session_id)     AS sessions,
       count_if(synthetic)            AS synthetic_events
FROM events
WHERE dt >= ?
