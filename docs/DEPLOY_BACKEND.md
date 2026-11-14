# Deploy the KISAN-X backend for an APK demo

This guide prepares a demo backend using Render for the FastAPI Docker service and a managed Postgres database. It does not publish the project or create hosting accounts for you.

## Before you start

The current prototype has no farmer accounts or per-farmer access control. Anyone can reach the public API, and farm records include field coordinates. Use demo data only; do not enter real farmer names, phone numbers, field boundaries, payment claims, or receipts on this public demo.

The free Render service sleeps after 15 minutes without traffic and can take about a minute to wake. Its filesystem is temporary, so uploaded QR and payment-proof images disappear after a restart or sleep. Render's own free Postgres expires after 30 days. For this demo, use a separate managed Postgres service such as Neon and leave owner payments unconfigured. Do not add a QR or UPI ID until persistent private file storage and access controls are in place.

## 1. Put the project in GitHub

Upload the project root (the folder containing `README.md`, `Dockerfile`, `render.yaml`, and `backend/`) to the team's repository. Check that `.env`, `*.db`, `.venv/`, `backend/data/payment_uploads/`, `work/`, and `outputs/` are excluded before committing. Never put a database password, owner PIN, or payment image in GitHub.

## 2. Create the Postgres database

Create a Postgres project on your chosen database provider. Copy its connection URL from the provider's dashboard and keep it private. For Neon, use the pooled URL if provided and confirm SSL is required. The app accepts standard `postgres://` and `postgresql://` URLs and selects the installed psycopg 3 driver automatically.

## 3. Create the backend service

1. Sign in to Render and choose **New → Blueprint**.
2. Connect the GitHub repository containing this project and select the branch to deploy.
3. Render reads the root `render.yaml`. At the prompt, paste the Postgres URL into `DATABASE_URL` and deploy the `kisanx-api` service.
4. Wait for the deploy to finish. Open the service URL and check `/health` returns `{"status":"ok","service":"kisan-x-api"}`.
5. Keep the generated `onrender.com` HTTPS origin. It is the value used to build the APK.

The service initializes the database tables on startup. Its default owner PIN is empty, which disables owner-only payment management. Keep it unset for this demo. Free hosting is suitable for a short prototype demonstration, not a production system with real farmer or payment records.

## 4. Build the APK

In the GitHub repository, open **Settings → Secrets and variables → Actions → Variables**, add variable `KISANX_API_BASE`, and set it to the backend's origin only, for example `https://kisanx-api.onrender.com` (no path or trailing `/api/v1`). Then open **Actions → Build Android APK and Windows installer → Run workflow**. Download the `KISAN-X-Android-debug-APK` artifact when the Android job succeeds.

The first API call after the free service sleeps can be slow. An APK built before the service has an HTTPS origin cannot use backend features until it is rebuilt with that origin.

## Limits before public or production use

- Add farmer authentication and per-farmer authorization before storing real profiles or coordinates.
- Use persistent private object storage for QR codes and payment proofs, and restrict payment administration to an authenticated owner.
- Set a strong `KISANX_OWNER_PIN` only after the storage and access controls are ready; do not commit it or put it in the APK.
- Configure backups, deletion/retention rules, abuse protection, and monitoring. A demo/free service may sleep, restart, or hit usage limits.
