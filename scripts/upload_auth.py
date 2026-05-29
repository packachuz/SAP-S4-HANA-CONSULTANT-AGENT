#!/usr/bin/env python3
"""Upload local NotebookLM auth state to Google Secret Manager.

Usage:
    python scripts/upload_auth.py [--project YOUR_PROJECT_ID] [--region asia-southeast1]

Run `notebooklm login` first to generate the local storage state, then run this
script to push it to Secret Manager so Cloud Run can use it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Deployment identifiers. These mirror deploy/config.sh — override via env so
# the shell scripts and this script always agree on a single source of truth.
SECRET_NAME = os.environ.get("SECRET_NAME", "NOTEBOOKLM_STORAGE_JSON")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "sap-consultant-agent")
MOUNT_PATH = os.environ.get("MOUNT_PATH", "/run/secrets/notebooklm-storage")
DEFAULT_REGION = os.environ.get("REGION", "asia-southeast1")

CANDIDATE_PATHS = [
    Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json",
    Path.home() / ".notebooklm" / "storage.json",
]


def _gcloud(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["gcloud", *args]
    try:
        if capture:
            return subprocess.run(cmd, capture_output=True, text=True)
        return subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("ERROR: gcloud CLI not found. Install the Google Cloud SDK:")
        print("  https://cloud.google.com/sdk/docs/install")
        sys.exit(1)


def find_storage() -> Path:
    for p in CANDIDATE_PATHS:
        if p.exists():
            return p
    print("ERROR: No NotebookLM storage state found in any of:")
    for p in CANDIDATE_PATHS:
        print(f"  {p}")
    print("\nRun `notebooklm login` first to authenticate, then re-run this script.")
    sys.exit(1)


def get_project(override: str | None) -> str:
    if override:
        return override
    result = _gcloud("config", "get-value", "project", capture=True)
    project = result.stdout.strip()
    if not project or project == "(unset)":
        print("ERROR: No GCP project configured.")
        print("Run: gcloud config set project YOUR_PROJECT_ID")
        sys.exit(1)
    return project


def upload_secret(storage_path: Path, project: str) -> None:
    size = storage_path.stat().st_size
    data_file = str(storage_path)

    describe = _gcloud(
        "secrets", "describe", SECRET_NAME,
        "--project", project,
        capture=True,
    )

    if describe.returncode == 0:
        _gcloud(
            "secrets", "versions", "add", SECRET_NAME,
            "--data-file", data_file,
            "--project", project,
        )
        print(f"Updated secret '{SECRET_NAME}' with new auth state ({size:,} bytes).")
    elif "NOT_FOUND" in describe.stderr:
        _gcloud(
            "secrets", "create", SECRET_NAME,
            "--data-file", data_file,
            "--replication-policy", "automatic",
            "--project", project,
        )
        print(f"Created secret '{SECRET_NAME}' ({size:,} bytes).")
    else:
        print(f"ERROR: could not query secret '{SECRET_NAME}' in project '{project}'.")
        print(describe.stderr.strip() or "(no error output from gcloud)")
        sys.exit(1)


def redeploy(project: str, region: str) -> None:
    print(f"\nRedeploying {SERVICE_NAME} to pick up the new secret...")
    _gcloud(
        "run", "services", "update", SERVICE_NAME,
        "--region", region,
        "--project", project,
        "--update-secrets", f"{MOUNT_PATH}={SECRET_NAME}:latest",
        "--update-env-vars", f"NOTEBOOKLM_STORAGE={MOUNT_PATH}",
    )
    print("Redeploy triggered. The new revision will use the updated auth state.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="GCP project ID (defaults to gcloud config)")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run region")
    parser.add_argument("--no-redeploy", action="store_true", help="Upload only; skip Cloud Run redeploy")
    args = parser.parse_args()

    storage_path = find_storage()
    print(f"Found storage state: {storage_path}")

    project = get_project(args.project)
    print(f"GCP project: {project}")

    upload_secret(storage_path, project)

    if not args.no_redeploy:
        redeploy(project, args.region)
    else:
        print("\nSkipped redeploy. To apply manually:")
        print(f"  gcloud run services update {SERVICE_NAME} \\")
        print(f"    --region {args.region} --project {project} \\")
        print(f"    --update-secrets {MOUNT_PATH}={SECRET_NAME}:latest \\")
        print(f"    --update-env-vars NOTEBOOKLM_STORAGE={MOUNT_PATH}")


if __name__ == "__main__":
    main()
