SELECT count(*)                       AS events,
       count(DISTINCT user_id)        AS users,
       count(DISTINCT session_id)     AS sessions,
       count_if(synthetic)            AS synthetic_events
FROM events
