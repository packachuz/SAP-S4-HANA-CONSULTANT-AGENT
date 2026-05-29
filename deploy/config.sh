# Shared Cloud Run deployment configuration.
#
# Source this from deploy scripts:   . "$(dirname "$0")/../deploy/config.sh"
# Every value can be overridden by exporting it before sourcing, so this file
# is the single source of truth shared with scripts/upload_auth.py.

SERVICE_NAME="${SERVICE_NAME:-sap-consultant-agent}"
REGION="${REGION:-asia-southeast1}"
SECRET_NAME="${SECRET_NAME:-NOTEBOOKLM_STORAGE_JSON}"
MOUNT_PATH="${MOUNT_PATH:-/run/secrets/notebooklm-storage}"

# Runtime sizing — Chromium (Playwright) needs real memory or NotebookLM calls
# silently fall back to STUB mode.
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-2}"
CONCURRENCY="${CONCURRENCY:-4}"
TIMEOUT="${TIMEOUT:-600}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"

# Optional: bucket for persisting RAG state (notebook registry, podcasts).
# Leave empty to keep state on the (ephemeral) container disk.
GCS_STATE_BUCKET="${GCS_STATE_BUCKET:-}"

# Export everything so child processes (e.g. scripts/upload_auth.py) inherit it.
export SERVICE_NAME REGION SECRET_NAME MOUNT_PATH
export MEMORY CPU CONCURRENCY TIMEOUT MIN_INSTANCES GCS_STATE_BUCKET
