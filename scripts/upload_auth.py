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
import tempfile
from pathlib import Path

SECRET_NAME = "NOTEBOOKLM_STORAGE_JSON"
SERVICE_NAME = "sap-consultant-agent"
MOUNT_PATH = "/run/secrets/notebooklm-storage"

CANDIDATE_PATHS = [
    Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json",
    Path.home() / ".notebooklm" / "storage.json",
]


def _gcloud(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["gcloud", *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True)
    return subprocess.run(cmd, check=True)


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
    content = storage_path.read_bytes()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(content)
        tmp = f.name

    try:
        exists = _gcloud(
            "secrets", "describe", SECRET_NAME,
            "--project", project,
            capture=True,
        ).returncode == 0

        if exists:
            _gcloud(
                "secrets", "versions", "add", SECRET_NAME,
                "--data-file", tmp,
                "--project", project,
            )
            print(f"Updated secret '{SECRET_NAME}' with new auth state ({len(content):,} bytes).")
        else:
            _gcloud(
                "secrets", "create", SECRET_NAME,
                "--data-file", tmp,
                "--replication-policy", "automatic",
                "--project", project,
            )
            print(f"Created secret '{SECRET_NAME}' ({len(content):,} bytes).")
    finally:
        os.unlink(tmp)


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
    parser.add_argument("--region", default="asia-southeast1", help="Cloud Run region")
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
        print(f"\nSkipped redeploy. To apply manually:")
        print(f"  gcloud run services update {SERVICE_NAME} --region {args.region} \\")
        print(f"    --update-secrets {MOUNT_PATH}={SECRET_NAME}:latest \\")
        print(f"    --update-env-vars NOTEBOOKLM_STORAGE={MOUNT_PATH}")


if __name__ == "__main__":
    main()
