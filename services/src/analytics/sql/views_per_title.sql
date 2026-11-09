-- How many viewing sessions started per title, and by how many different people.
SELECT title_id,
       count(DISTINCT session_id) AS views,
       count(DISTINCT user_id)    AS unique_viewers
FROM events
WHERE type = 'play'
GROUP BY title_id
ORDER BY views DESC
