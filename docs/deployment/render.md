# Deploying the demo to Render

One container (API plus the built web app) and one Postgres database, described by `render.yaml` at the repository root. Free plans: this is a demo, not a production deployment.

**Status: not deployed yet.** The image has been built and run locally in the same way Render runs it, and the browser end-to-end test passes against it. `render.yaml` has not been read by Render yet, so the first Blueprint sync is the first real test of that file.

## What you need

- A Render account connected to the GitHub account that can read this repository.
- The code on GitHub, on the branch Render will deploy (normally `main`).

Sign in to Render yourself. Do not put Render or GitHub passwords in chat, in the repository, or in any file.

## First deployment

1. Push the code. From the repository root, after committing:

   ```bash
   git push -u origin feature/s5-early-demo
   ```

   Open a pull request into `main`, wait for the three CI jobs (`api`, `web`, `e2e`) to pass, and merge. This is the first time CI runs for this project, so expect to fix something small.

2. In the Render dashboard: **New > Blueprint**, pick this repository and the `main` branch. Render reads `render.yaml` and shows one database (`mls-db`) and one web service (`ai-native-mls`). Confirm.

3. Wait for the first deploy. The container start runs the database migrations, then creates the demo data, then starts the server. The first build takes several minutes.

4. Read the demo password: service `ai-native-mls` > **Environment** > `SEED_PASSWORD`. Render generated it; it exists nowhere else. Every demo account uses it.

5. Open the service URL (shown at the top of the service page, ending `.onrender.com`). Sign in as `sunrise.admin@demo.example.com` with that password. The other demo accounts are listed in the README.

6. Run the browser test against the live site, from `apps/web`:

   ```bash
   E2E_BASE_URL=https://<your-service>.onrender.com E2E_PASSWORD='<the SEED_PASSWORD value>' pnpm e2e
   ```

   It creates one listing and archives it again.

7. Put the URL in the README's status line.

## What the settings mean

| Variable | Value on Render | Purpose |
|---|---|---|
| `DATABASE_URL` | from `mls-db` | Render gives a `postgresql://` URL; the app adds the driver name itself. |
| `ENVIRONMENT` | `production` | `Secure` session cookie; API docs page off. |
| `SEED_DEMO_DATA` | `true` | Create demo organisations, users and listings at start if missing. Set to `false` to stop. |
| `SEED_PASSWORD` | generated | Password for the demo accounts. Changing it later does not change existing accounts. |
| `MEDIA_SIGNING_KEY` | generated | Signs short-lived media download links. The app refuses to start in production without it. |
| `MEDIA_STORAGE` | `local` (not set) | Uploaded files go on the container's disk, which Render's free plan wipes on every deploy or restart. For files that last, create a private S3-compatible bucket (for example Cloudflare R2 or AWS S3) and add `MEDIA_STORAGE=s3`, `MEDIA_S3_BUCKET`, `MEDIA_S3_ENDPOINT_URL` (not needed for AWS), `MEDIA_S3_REGION`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the dashboard. Never put these in `render.yaml`. |
| `FORWARDED_ALLOW_IPS` | `*` | Trust Render's proxy for the client address. |
| `PORT` | set by Render | The port the server listens on. |

The container also runs the background job worker (`python -m app.worker`, started by `start.sh`); it makes thumbnails and deletes removed files. A free service that sleeps runs no jobs while asleep; they run when it wakes.

## Later deployments

Every push to the deployed branch rebuilds and redeploys. Migrations run at each start; seeding skips what already exists.

## Rollback

Render dashboard > service > **Events** (or **Deploys**) > choose the last good deploy > **Rollback**. This rolls back code only. Migrations so far only add tables, so older code keeps working against a newer database. A migration that changes or drops something will need its own rollback note.

## Known limits of this demo deployment

- The free service sleeps when idle; the first request after that takes up to a minute.
- Render's free Postgres is temporary and is deleted after a limited period (check the current terms in the dashboard). There are no backups. Treat all demo data as disposable.
- `FORWARDED_ALLOW_IPS=*` trusts the forwarded client address from any source. That is acceptable only because the container is reachable solely through Render's proxy. The sign-in rate limit per IP address depends on it.
- No custom domain, no error monitoring, no alerts (Sprint 21).
- Demo accounts share one password. Anyone who has it can sign in as the platform administrator of the demo. Share it only with reviewers, and do not put real data in the demo.
- Uploaded media (Sprint 6) will need object storage; the container's disk is not kept between deploys.

## Running the same image locally

```bash
docker compose up -d --wait
docker build -t ai-native-mls:local .
docker run --rm -p 127.0.0.1:8000:8000 \
  --network ai-native-mls_default \
  -e DATABASE_URL=postgres://mls:mls@postgres:5432/mls \
  ai-native-mls:local
```

Open http://localhost:8000. This uses your local development database and its seed accounts.
