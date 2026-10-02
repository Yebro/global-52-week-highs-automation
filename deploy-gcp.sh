#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:?Usage: ./deploy-gcp.sh PROJECT_ID}"
REGION="${REGION:-asia-northeast3}"
BUCKET="${STATE_BUCKET:-${PROJECT_ID}-global-highs}"
REPOSITORY="global-highs"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/tracker:latest"
WEB_SERVICE="global-highs-tracker"
ASIA_JOB="global-highs-asia"
US_JOB="global-highs-us"
MANUAL_JOB="global-highs-manual"
JOB_SA="global-highs-job@${PROJECT_ID}.iam.gserviceaccount.com"
WEB_SA="global-highs-web@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="global-highs-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com

if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
fi

if ! gcloud artifacts repositories describe "${REPOSITORY}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --location="${REGION}" \
    --repository-format=docker \
    --description="Global 52-week highs tracker images"
fi

create_service_account() {
  local name="$1"
  local description="$2"
  if ! gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${name}" --display-name="${description}"
  fi
}

create_service_account "global-highs-job" "Global highs collector"
create_service_account "global-highs-web" "Global highs dashboard"
create_service_account "global-highs-scheduler" "Global highs scheduler"

for secret in telegram-bot-token telegram-chat-id; do
  if ! gcloud secrets describe "${secret}" >/dev/null 2>&1; then
    echo "Missing Secret Manager secret: ${secret}" >&2
    echo "Create both secrets before running this script." >&2
    exit 2
  fi
done

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/storage.objectAdmin" >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${WEB_SA}" \
  --role="roles/storage.objectViewer" >/dev/null

for secret in telegram-bot-token telegram-chat-id; do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --member="serviceAccount:${JOB_SA}" \
    --role="roles/secretmanager.secretAccessor" >/dev/null
done

gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions="_IMAGE=${IMAGE}" \
  .

gcloud run deploy "${WEB_SERVICE}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${WEB_SA}" \
  --command=gunicorn \
  --args="--bind=:8080,--workers=2,--threads=4,serve_dashboard:app" \
  --set-env-vars="STATE_BUCKET=${BUCKET}" \
  --cpu=1 \
  --memory=512Mi \
  --min=0 \
  --max=2 \
  --timeout=60 \
  --allow-unauthenticated \
  --quiet

DASHBOARD_URL="$(gcloud run services describe "${WEB_SERVICE}" --region="${REGION}" --format='value(status.url)')/"

deploy_job() {
  local job_name="$1"
  local slot="$2"
  gcloud run jobs deploy "${job_name}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --service-account="${JOB_SA}" \
    --command=python \
    --args="cloud_run_job.py,--slot,${slot},--attempts,5,--interval-seconds,60" \
    --set-env-vars="STATE_BUCKET=${BUCKET},DASHBOARD_URL=${DASHBOARD_URL}" \
    --set-secrets="TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,TELEGRAM_CHAT_ID=telegram-chat-id:latest" \
    --cpu=2 \
    --memory=4Gi \
    --task-timeout=30m \
    --max-retries=1 \
    --quiet
}

deploy_job "${ASIA_JOB}" asia
deploy_job "${US_JOB}" us
deploy_job "${MANUAL_JOB}" manual

for job_name in "${ASIA_JOB}" "${US_JOB}"; do
  gcloud run jobs add-iam-policy-binding "${job_name}" \
    --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" >/dev/null
done

upsert_schedule() {
  local scheduler_name="$1"
  local schedule="$2"
  local target_job="$3"
  local uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${target_job}:run"
  local common=(
    --location="${REGION}"
    --schedule="${schedule}"
    --time-zone="Asia/Seoul"
    --uri="${uri}"
    --http-method=POST
    --oauth-service-account-email="${SCHEDULER_SA}"
    --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
    --headers="Content-Type=application/json"
    --message-body="{}"
    --attempt-deadline=30m
    --max-retry-attempts=3
    --min-backoff=60s
    --max-backoff=60s
    --max-doublings=0
  )
  if gcloud scheduler jobs describe "${scheduler_name}" --location="${REGION}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${scheduler_name}" "${common[@]}"
  else
    gcloud scheduler jobs create http "${scheduler_name}" "${common[@]}"
  fi
}

# Asia closes on the same KST date. US Friday close is published Saturday KST.
upsert_schedule "global-highs-asia-1600" "0 16 * * 1-5" "${ASIA_JOB}"
upsert_schedule "global-highs-us-0800" "0 8 * * 2-6" "${US_JOB}"

echo "Dashboard: ${DASHBOARD_URL}"
echo "Manual test: gcloud run jobs execute ${MANUAL_JOB} --region=${REGION} --wait"
