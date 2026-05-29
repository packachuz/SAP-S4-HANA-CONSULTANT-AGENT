#!/usr/bin/env bash
#
# Local go/no-go check before deploying to the cloud.
#
#   ./scripts/smoke_test.sh
#
# Installs deps, ensures Chromium is present, verifies a NotebookLM session
# exists, then confirms the wrapper connects in LIVE (not STUB) mode. If this
# passes locally, the Cloud Run deploy will work too.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

echo "==> Installing Python dependencies..."
pip install --quiet -r requirements.txt

echo "==> Ensuring Chromium is installed for Playwright..."
playwright install chromium >/dev/null

echo "==> Checking for a NotebookLM session..."
if [ ! -f "$HOME/.notebooklm/profiles/default/storage_state.json" ] && \
   [ ! -f "$HOME/.notebooklm/storage.json" ]; then
  echo "ERROR: No NotebookLM session found. Run 'notebooklm login' first."
  exit 1
fi

echo "==> Probing the NotebookLM wrapper (REQUIRE_LIVE)..."
# NOTEBOOKLM_REQUIRE_LIVE=1 makes a failed connect return False instead of
# silently degrading to STUB, so this check is meaningful.
NOTEBOOKLM_REQUIRE_LIVE=1 python - <<'PY'
import asyncio, sys
from src.notebooklm_client import NotebookLMClientWrapper

async def main():
    client = NotebookLMClientWrapper()
    info = await client.auth_check()
    print("auth_check:", info)
    mode = info.get("mode")
    if mode != "LIVE":
        print(f"\nNOT LIVE (mode={mode}). Fix auth/deps before deploying.")
        sys.exit(1)
    print("\nLIVE — ready to deploy. Next: ./scripts/deploy.sh PROJECT_ID")

asyncio.run(main())
PY
