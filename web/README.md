# bhavs web app

Next.js (App Router) front end for bhavs, deployed on Vercel. See the [main README](../README.md) for the whole system.

- `npm run dev`: local dev server (needs `.env.local`, see `.env.example`).
- `npm run build && npm run start -- -p 3100`: production build locally.
- `npm run e2e`: signed-out Playwright checks against `E2E_BASE_URL` (default `http://localhost:3100`).
- `npm run e2e:journey`: login -> browse -> search -> play -> resume (needs `E2E_EMAIL` / `E2E_PASSWORD`).
