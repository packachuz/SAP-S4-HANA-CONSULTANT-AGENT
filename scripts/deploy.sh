#!/usr/bin/env bash
#
# First-time (and repeatable) Cloud Run bring-up for the SAP Consultant Agent.
#
#   ./scripts/deploy.sh [PROJECT_ID]
#
# Idempotent: enables APIs, builds the image, deploys the service with sane
# runtime sizing, grants the runtime service account access to the auth secret
# (and the state bucket, if configured), then pushes the NotebookLM session.
#
# Run `notebooklm login` locally first so the auth upload has something to push.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=../deploy/config.sh
. "$ROOT/deploy/config.sh"

# --- resolve project -------------------------------------------------------
PROJECT_ID="${1:-${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}}"
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
  echo "ERROR: No GCP project. Pass one (./scripts/deploy.sh PROJECT_ID) or run:"
  echo "  gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
echo "Project:  $PROJECT_ID"
echo "Service:  $SERVICE_NAME ($REGION)"
echo "Image:    $IMAGE"

# --- enable APIs -----------------------------------------------------------
echo "==> Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  containerregistry.googleapis.com \
  --project "$PROJECT_ID"

# --- build image -----------------------------------------------------------
echo "==> Building image with Cloud Build..."
gcloud builds submit "$ROOT" --tag "$IMAGE" --project "$PROJECT_ID"

# --- deploy ----------------------------------------------------------------
ENV_VARS="NOTEBOOKLM_REQUIRE_LIVE=1"
if [ -n "$GCS_STATE_BUCKET" ]; then
  ENV_VARS="${ENV_VARS},GCS_STATE_BUCKET=${GCS_STATE_BUCKET}"
fi

echo "==> Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory "$MEMORY" \
  --cpu "$CPU" \
  --concurrency "$CONCURRENCY" \
  --timeout "$TIMEOUT" \
  --min-instances "$MIN_INSTANCES" \
  --set-env-vars "$ENV_VARS"

# --- grant the runtime service account access -----------------------------
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "==> Granting secret access to $RUNTIME_SA..."
# The secret may not exist yet on a first run; upload_auth.py creates it below,
# so bind at the project level which applies once the secret is created.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNTIME_SA}" \
  --role "roles/secretmanager.secretAccessor" \
  --condition=None >/dev/null

if [ -n "$GCS_STATE_BUCKET" ]; then
  echo "==> Granting bucket access (gs://$GCS_STATE_BUCKET)..."
  gcloud storage buckets add-iam-policy-binding "gs://${GCS_STATE_BUCKET}" \
    --member "serviceAccount:${RUNTIME_SA}" \
    --role "roles/storage.objectAdmin" >/dev/null || \
    echo "WARN: could not bind bucket IAM — create the bucket and grant manually."
fi

# --- push NotebookLM auth + redeploy to mount it ---------------------------
echo "==> Uploading NotebookLM auth session..."
python "$HERE/upload_auth.py" --project "$PROJECT_ID" --region "$REGION"

URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" \
  --project "$PROJECT_ID" --format='value(status.url)' 2>/dev/null || true)"
echo ""
echo "Done. Service URL: ${URL:-<run: gcloud run services describe $SERVICE_NAME>}"
