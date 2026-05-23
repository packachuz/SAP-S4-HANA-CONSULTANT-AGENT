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
