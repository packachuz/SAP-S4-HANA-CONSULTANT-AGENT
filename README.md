# SAP S/4HANA Consultant Agent Team Orchestrator

A multi-agent system that simulates a senior SAP consulting team:

- **MD** (Managing Director) — coordinates requests, decomposes them into
  module sub-queries, and synthesises the final executive deliverable.
- **MM, SD, FI, CO, HCM, ARIBA** — domain-specific agents, each grounded
  in its own NotebookLM notebook (`SAP-MM-KB`, `SAP-FI-KB`, …) built from
  standard SAP PDFs and dynamic web research.

Built with **Python 3.10+ asyncio**, the unofficial **`notebooklm-py`**
client for RAG + audio overviews, **`google-genai`** for MD planning and
synthesis, and a **Streamlit** dashboard.

---

## Project layout

```
.
├── config/                 # System prompts (one per agent)
│   ├── md_prompt.txt
│   ├── mm_prompt.txt
│   ├── sd_prompt.txt
│   ├── fi_prompt.txt
│   ├── co_prompt.txt
│   ├── hcm_prompt.txt
│   └── ariba_prompt.txt
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py       # shared scaffolding
│   │   ├── md_agent.py         # planner + synthesiser
│   │   └── module_agents.py    # MM, SD, FI, CO, HCM, ARIBA
│   ├── notebooklm_client.py    # async wrapper around notebooklm-py
│   ├── orchestrator.py         # MD → module agents → synthesis → podcast
│   └── utils.py                # logging, prompt loading, event bus
├── app.py                      # Streamlit dashboard
└── requirements.txt
```

---

## Setup

1. **Install Python deps**

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Authenticate NotebookLM** (one-time per machine)

   ```bash
   notebooklm login
   ```

   The browser session is persisted to `~/.notebooklm/storage.json`. The
   app reuses this; you don't need to log in again per run.

3. **(Optional) Set the LLM API key** for the MD planner / synthesiser

   ```bash
   export GOOGLE_API_KEY=...
   ```

   Without a key the orchestrator falls back to a deterministic
   heuristic planner so the end-to-end flow still runs.

4. **Run the dashboard**

   ```bash
   streamlit run app.py
   ```

---

## Deploy to Cloud Run

The app is browser-driven (Playwright/Chromium) and needs a logged-in
NotebookLM session, so the cloud flow is: **authenticate locally → ship the
session to Secret Manager → mount it into Cloud Run.**

### First-time bring-up (one command)

```bash
notebooklm login                 # 1. authenticate locally (opens a browser)
./scripts/deploy.sh PROJECT_ID   # 2. enable APIs, build, deploy, mount auth
```

`deploy.sh` enables the required APIs, builds the image with Cloud Build,
deploys to Cloud Run with sensible sizing (2Gi / 2 vCPU so Chromium doesn't
OOM into STUB), grants the runtime service account access to the auth secret,
then calls `scripts/upload_auth.py` to push the session.

Tunables (service name, region, memory, etc.) live in `deploy/config.sh` and
can be overridden via environment variables.

### Refreshing auth (cookies expire every few weeks)

```bash
notebooklm login
python scripts/upload_auth.py    # re-upload + redeploy
```

### Automated deploys (CI/CD)

`.github/workflows/deploy.yml` builds and deploys on every push to `master`.
It never touches the auth secret (cookies stay out of CI logs). Configure two
repository secrets:

| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | your GCP project id |
| `GCP_SA_KEY` | JSON key for a service account with Cloud Run / Cloud Build / Storage Admin roles |

> Prefer **Workload Identity Federation** over a long-lived key? Replace the
> `auth` step's `credentials_json` with `workload_identity_provider` +
> `service_account` — see the
> [google-github-actions/auth](https://github.com/google-github-actions/auth) docs.

### Durable RAG state

Cloud Run's disk is ephemeral, so set `GCS_STATE_BUCKET` (in `deploy/config.sh`
or as an env var) to persist the notebook registry and generated podcasts to
Cloud Storage. Without it, notebook IDs are lost on restart and modules get
re-provisioned.

---

## Dashboard tabs

| Tab | What it does |
|-----|--------------|
| **Configuration** | Shows live auth status, exposes the terminal `notebooklm auth check --test` command, lists the agent roster. |
| **Knowledge Base** | Pick a module → provision its notebook, upload standard SAP PDF manuals, sync (re-index), and trigger dynamic web research. |
| **Workspace** | Enter the engagement description, watch the step-by-step orchestrator trace, read the final Markdown deliverable, and play / download the briefing podcast. |

---

## Stub mode

If `notebooklm-py` (or its browser deps) is missing, the app degrades to
**STUB mode**: every NotebookLM call returns realistic placeholder data,
including a tiny silent MP3 in place of the podcast. This lets you
develop and demo the orchestration flow without a live session.

You'll see a `NotebookLM · STUB` pill in the header when this is the
case; install the deps and run `notebooklm login` to switch to `LIVE`.

---

## Programmatic use

```python
import asyncio
from src.orchestrator import Orchestrator

async def main():
    orch = Orchestrator()
    result = await orch.run(
        "Help me design the P2P process for a new S/4HANA rollout with Ariba.",
        generate_podcast=True,
    )
    print(result.final_markdown)
    print("Podcast at:", result.podcast.file_path)

asyncio.run(main())
```

---

## Notes

- All NotebookLM operations are async; the wrapper offloads the
  underlying synchronous browser-driven calls via `asyncio.to_thread`.
- The MD's delegation plan is emitted as a fenced ```delegation``` JSON
  block — easy to inspect, log, and replay.
- Notebook IDs per module are persisted to
  `data/notebook_registry.json`, so provisioning happens at most once
  per module.
