"""Streamlit dashboard for the SAP S/4HANA Consultant Agent Team Orchestrator.

Run:  streamlit run app.py
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os
import shlex
import site
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add python scripts/bin directory to PATH dynamically so the subprocesses can find 'notebooklm'
def _patch_path():
    paths_to_add = []
    if sys.platform == "win32":
        if hasattr(site, "getuserbase"):
            user_base = site.getuserbase()
            if user_base:
                py_ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
                paths_to_add.append(str(Path(user_base) / py_ver / "Scripts"))
                paths_to_add.append(str(Path(user_base) / "Scripts"))
        paths_to_add.append(str(Path(sys.executable).parent / "Scripts"))
        paths_to_add.append(str(Path(sys.exec_prefix) / "Scripts"))
    else:
        if hasattr(site, "getuserbase"):
            user_base = site.getuserbase()
            if user_base:
                paths_to_add.append(str(Path(user_base) / "bin"))
        paths_to_add.append(str(Path(sys.executable).parent / "bin"))
        paths_to_add.append(str(Path(sys.exec_prefix) / "bin"))
    
    existing_path = os.environ.get("PATH", "")
    path_sep = ";" if sys.platform == "win32" else ":"
    new_paths = [p for p in paths_to_add if Path(p).exists()]
    if new_paths:
        os.environ["PATH"] = path_sep.join(new_paths) + path_sep + existing_path

_patch_path()

import streamlit as st

from src.agents import ALL_MODULE_AGENTS
from src.notebooklm_client import MODULE_NOTEBOOKS, get_client
from src.orchestrator import OrchestrationResult, run_sync
from src.utils import (
    KB_DIR,
    PODCAST_DIR,
    EventBus,
    OrchestratorEvent,
    get_notebook_registry,
)

# ---------------------------------------------------------------------------
# Page config + theme
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SAP S/4HANA Consultant Agent Team",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Original, non-branded styling — restrained, consultancy-feel.
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    :root {
        --bg: #0b0f17;
        --panel: rgba(22, 26, 38, 0.65);
        --panel-2: rgba(30, 36, 52, 0.8);
        --border: rgba(42, 51, 74, 0.45);
        --border-active: rgba(114, 170, 255, 0.55);
        --ink: #f1f3f7;
        --ink-dim: #9fb2cd;
        --accent: #58a6ff;
        --accent-2: #38d39f;
        --warn: #ffd866;
    }
    
    html, body, [class*="css"] { 
        font-family: "Plus Jakarta Sans", "Inter", sans-serif; 
    }
    
    .stApp {
        background-image: radial-gradient(circle at 10% 20%, #0d121f 0%, #080a10 100%);
    }

    .block-container { 
        padding-top: 1.5rem; 
        padding-bottom: 4rem; 
        max-width: 1400px; 
    }
    
    h1, h2, h3, h4 { 
        letter-spacing: -0.02em; 
        font-weight: 700;
    }
    
    .title-gradient {
        background: linear-gradient(135deg, #ffffff 0%, #a2c6ff 50%, #58a6ff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.4rem;
        letter-spacing: -0.03em;
        margin-bottom: 2px;
    }

    .stTabs [data-baseweb="tab-list"] { 
        gap: 0.5rem; 
        border-bottom: 1px solid var(--border);
        padding-bottom: 4px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 46px; 
        padding: 0 20px;
        background: transparent; 
        border-radius: 8px;
        color: var(--ink-dim); 
        font-weight: 600;
        font-size: 14px;
        border: 1px solid transparent;
        transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1);
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--ink);
        background: rgba(255, 255, 255, 0.03);
    }

    .stTabs [aria-selected="true"] {
        background: rgba(88, 166, 255, 0.08) !important; 
        color: var(--accent) !important;
        border: 1px solid var(--border) !important;
        box-shadow: 0 4px 12px rgba(88, 166, 255, 0.05);
    }
    
    .panel {
        background: var(--panel); 
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid var(--border);
        border-radius: 16px; 
        padding: 24px; 
        margin-bottom: 16px;
        box-shadow: 0 10px 30px 0 rgba(0, 0, 0, 0.25);
    }
    
    .pill {
        display: inline-block; 
        padding: 4px 12px; 
        border-radius: 99px;
        font-size: 11px; 
        font-weight: 700; 
        border: 1px solid var(--border);
        color: var(--ink-dim);
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    
    .pill.ok { 
        background: rgba(56, 211, 159, 0.1); 
        color: #38d39f; 
        border-color: rgba(56, 211, 159, 0.3); 
        box-shadow: 0 0 12px rgba(56, 211, 159, 0.08);
    }
    
    .pill.warn { 
        background: rgba(255, 216, 102, 0.1);  
        color: #ffd866; 
        border-color: rgba(255, 216, 102, 0.3); 
        box-shadow: 0 0 12px rgba(255, 216, 102, 0.08);
    }
    
    .pill.err { 
        background: rgba(255, 107, 107, 0.1); 
        color: #ff6b6b; 
        border-color: rgba(255, 107, 107, 0.3); 
        box-shadow: 0 0 12px rgba(255, 107, 107, 0.08);
    }
    
    .pill.stub { 
        background: rgba(88, 166, 255, 0.1); 
        color: #58a6ff; 
        border-color: rgba(88, 166, 255, 0.3); 
        box-shadow: 0 0 12px rgba(88, 166, 255, 0.08);
    }
    
    .kbd {
        font-family: "JetBrains Mono", monospace;
        font-size: 11px; 
        background: #06090e; 
        border: 1px solid var(--border);
        padding: 3px 6px; 
        border-radius: 6px; 
        color: var(--accent);
    }
    
    .agent-tile {
        background: var(--panel-2); 
        border: 1px solid var(--border);
        border-radius: 14px; 
        padding: 18px 20px;
        transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
    }
    
    .agent-tile:hover {
        transform: translateY(-4px);
        border-color: var(--border-active);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.3), 0 0 20px rgba(88, 166, 255, 0.12);
        background: rgba(36, 44, 64, 0.95);
    }
    
    .agent-tile h4 { 
        margin: 0 0 6px 0; 
        font-size: 16px; 
        color: var(--ink); 
        font-weight: 700;
    }
    
    .agent-tile p { 
        margin: 0; 
        font-size: 12px; 
        color: var(--ink-dim); 
        line-height: 1.4;
    }
    
    .small-muted { 
        color: var(--ink-dim); 
        font-size: 12px; 
    }
    
    .log-row {
        font-family: "JetBrains Mono", monospace; 
        font-size: 11px;
        padding: 10px 14px; 
        border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        display: flex;
        align-items: center;
        gap: 12px;
        transition: background 0.2s ease;
    }
    
    .log-row:hover {
        background: rgba(255, 255, 255, 0.02);
    }
    
    .log-actor { 
        display: inline-block; 
        min-width: 70px; 
        color: var(--accent); 
        font-weight: 600;
    }
    
    .log-phase { 
        display: inline-block; 
        min-width: 90px; 
        color: var(--accent-2); 
    }
    
    .stButton > button {
        border-radius: 10px; 
        border: 1px solid var(--border);
        background: linear-gradient(135deg, rgba(30, 36, 52, 0.5) 0%, rgba(22, 26, 38, 0.5) 100%); 
        color: var(--ink);
        font-weight: 600;
        padding: 8px 16px;
        transition: all 0.25s ease;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
    }
    
    .stButton > button:hover {
        border-color: var(--accent); 
        color: var(--ink);
        box-shadow: 0 4px 18px rgba(88, 166, 255, 0.15);
        transform: translateY(-1px);
    }
    
    .stButton > button:active {
        transform: translateY(1px);
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def _ss(key: str, default: Any) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


_ss("orchestration_result", None)
_ss("event_log", [])
_ss("auth_status", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run_async(coro):
    """Synchronously run an async coroutine inside Streamlit."""
    return asyncio.run(coro)


def render_header():
    col_l, col_r = st.columns([0.7, 0.3])
    with col_l:
        st.markdown(
            "<h1 class='title-gradient'>SAP S/4HANA Consultant Agent Team</h1>"
            "<div class='small-muted' style='margin-top: -6px;'>"
            "Multi-agent orchestrator · MD coordinates MM · SD · FI · CO · HCM · ARIBA"
            "</div>",
            unsafe_allow_html=True,
        )
    with col_r:
        client = get_client()
        mode = "STUB" if client.stub_mode else "LIVE"
        pill_class = "stub" if client.stub_mode else "ok"
        st.markdown(
            f"<div style='text-align:right;padding-top:12px'>"
            f"<span class='pill {pill_class}'>NotebookLM · {mode}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<hr style='border-color:rgba(42,51,74,0.45);margin:14px 0 22px'/>",
                unsafe_allow_html=True)


# =============================================================================
# TAB 1: Configuration
# =============================================================================
def render_configuration_tab():
    client = get_client()

    st.subheader("Authentication")
    st.markdown(
        "<div class='small-muted'>"
        "The orchestrator uses <span class='kbd'>notebooklm-py</span> in browser mode. "
        "Authenticate once locally with <span class='kbd'>notebooklm login</span> — "
        "your storage state is then reused here."
        "</div>",
        unsafe_allow_html=True,
    )

    cA, cB, cC = st.columns([1, 1, 1])
    with cA:
        if st.button("Run auth check", use_container_width=True):
            st.session_state.auth_status = run_async(client.auth_check())
    with cB:
        if st.button("Run `notebooklm auth check --test`", use_container_width=True):
            st.session_state.auth_status = _shell_auth_check()
    with cC:
        if st.button("Reset notebook registry", use_container_width=True):
            from src.utils import REGISTRY_PATH
            if REGISTRY_PATH.exists():
                REGISTRY_PATH.unlink()
            st.success("Registry cleared.")

    status = st.session_state.auth_status
    if status:
        ok = bool(status.get("ok"))
        mode = status.get("mode", "UNKNOWN")
        pill = "ok" if ok and mode == "LIVE" else ("stub" if mode == "STUB" else "err")
        st.markdown(
            f"<div class='panel'>"
            f"<span class='pill {pill}'>{mode}</span> &nbsp;"
            f"{status.get('message') or status.get('storage_path', '')}"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Raw status payload"):
            st.json(status)

    st.subheader("Terminal login check")
    st.markdown(
        "<div class='small-muted'>Runs in a subprocess — output streamed below.</div>",
        unsafe_allow_html=True,
    )
    default_cmd = "notebooklm auth check --test"
    cmd = st.text_input("Command", value=default_cmd, label_visibility="collapsed")
    if st.button("Run command"):
        with st.spinner(f"Running `{cmd}`…"):
            rc, out = _run_shell(cmd)
        st.markdown(
            f"<div class='small-muted'>Exit code: <span class='kbd'>{rc}</span></div>",
            unsafe_allow_html=True,
        )
        st.code(out or "(no output)", language="bash")

    st.subheader("Agent roster")
    cols = st.columns(3)
    info = {
        "MD":    ("Managing Director",      "Plans, delegates, synthesizes."),
        "MM":    ("Materials Management",   "EKKO · EKPO · EBAN · MARA"),
        "SD":    ("Sales & Distribution",   "VBAK · VBAP · LIKP · VBRK"),
        "FI":    ("Financial Accounting",   "ACDOCA · BSEG · ANLA"),
        "CO":    ("Controlling",            "ACDOCA · CSKS · AUFK"),
        "HCM":   ("Human Capital Mgmt",     "PA0000-0999 · HRP1001"),
        "ARIBA": ("SAP Ariba",              "cXML · /ARBA/* · CIG"),
    }
    for i, (k, (name, tables)) in enumerate(info.items()):
        with cols[i % 3]:
            st.markdown(
                f"<div class='agent-tile'>"
                f"<h4>{k} · {name}</h4>"
                f"<p>{tables}</p>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _shell_auth_check() -> Dict[str, Any]:
    rc, out = _run_shell("notebooklm auth check --test")
    return {
        "ok": rc == 0,
        "mode": "LIVE" if rc == 0 else "DISCONNECTED",
        "message": out.strip()[:600] or f"exit code {rc}",
    }


def _run_shell(cmd: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as exc:
        return 127, f"command not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "command timed out after 30s"
    except Exception as exc:
        return 1, f"{exc!r}"


# =============================================================================
# TAB 2: Knowledge Base
# =============================================================================
def render_knowledge_base_tab():
    client = get_client()

    left, right = st.columns([0.4, 0.6])

    with left:
        st.subheader("Module")
        module = st.radio(
            "Pick a module to manage",
            options=list(MODULE_NOTEBOOKS.keys()),
            format_func=lambda m: f"{m}  ·  {MODULE_NOTEBOOKS[m]}",
            label_visibility="collapsed",
        )
        registry = get_notebook_registry()
        nb_id = registry.get(module)
        pill = "ok" if nb_id else "warn"
        st.markdown(
            f"<div class='panel'>"
            f"<div class='small-muted'>Notebook</div>"
            f"<h4 style='margin:4px 0'>{MODULE_NOTEBOOKS[module]}</h4>"
            f"<span class='pill {pill}'>{nb_id or 'not provisioned'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("Provision / fetch notebook", use_container_width=True):
            with st.spinner("Contacting NotebookLM…"):
                nb_id = run_async(client.get_or_create_notebook(module))
            st.success(f"Notebook ready: {nb_id}")

        if st.button("Sync notebook (re-index)", use_container_width=True):
            with st.spinner("Syncing…"):
                res = run_async(client.sync_notebook(module))
            st.json(res)

    with right:
        st.subheader("Upload standard SAP PDF manuals")
        files = st.file_uploader(
            "Drag-and-drop one or more PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if files and st.button(f"Upload {len(files)} file(s) → {MODULE_NOTEBOOKS[module]}",
                               use_container_width=True):
            results = []
            for f in files:
                tmp = KB_DIR / module / f.name
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_bytes(f.read())
                with st.spinner(f"Uploading {f.name}…"):
                    res = run_async(client.upload_pdf(module, tmp))
                results.append({"file": f.name, **res})
            st.success(f"Uploaded {len(results)} file(s).")
            st.json(results)

        st.markdown("##### Local cache")
        cache_dir = KB_DIR / module
        cached = sorted(cache_dir.glob("*.pdf")) if cache_dir.exists() else []
        if not cached:
            st.markdown(
                "<div class='small-muted'>No PDFs cached locally yet.</div>",
                unsafe_allow_html=True,
            )
        else:
            for p in cached:
                size_kb = p.stat().st_size / 1024
                st.markdown(
                    f"<div class='log-row'>"
                    f"<span class='log-actor'>PDF</span> "
                    f"{p.name} <span class='small-muted'>({size_kb:,.0f} KB)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("---")
        st.subheader("Dynamic web research")
        st.markdown(
            "<div class='small-muted'>"
            "Trigger NotebookLM's web-discovery to enrich this notebook with current sources."
            "</div>",
            unsafe_allow_html=True,
        )
        kw = st.text_input(
            "Keywords",
            placeholder=f"e.g. S/4HANA {module} 2024 best practices",
            label_visibility="collapsed",
        )
        if st.button("Run web research", use_container_width=True, disabled=not kw):
            with st.spinner("Discovering sources…"):
                res = run_async(client.web_research(module, kw))
            st.json(res)


# =============================================================================
# TAB 3: Workspace
# =============================================================================
def render_workspace_tab():
    st.subheader("Project requirements")
    default_req = (
        "Client is a mid-market manufacturer migrating from ECC 6.0 to S/4HANA 2023. "
        "They need a recommendation on redesigning their procurement process, "
        "harmonising vendor master with Business Partner, and ensuring real-time "
        "financial postings remain reconciled with controlling. Highlight Ariba "
        "integration options for strategic sourcing."
    )
    request = st.text_area(
        "Describe the engagement",
        value=default_req,
        height=160,
        label_visibility="collapsed",
    )

    c1, c2, c3 = st.columns([0.25, 0.25, 0.5])
    with c1:
        gen_pod = st.checkbox("Generate briefing podcast", value=True)
    with c2:
        pod_module = st.selectbox(
            "Podcast module",
            options=["(auto)"] + list(ALL_MODULE_AGENTS.keys()),
            label_visibility="collapsed",
        )
    with c3:
        st.markdown("&nbsp;")

    run = st.button("▶  Run orchestrator", type="primary", use_container_width=True)

    if run and request.strip():
        st.session_state.event_log = []
        bus = EventBus()
        bus.subscribe(lambda e: st.session_state.event_log.append(e))

        progress = st.progress(0, text="Initialising…")
        log_placeholder = st.empty()

        # Streamlit can't easily render mid-run async events without a background
        # thread. We run synchronously and render the captured log afterwards;
        # the bus has already accumulated every step for full traceability.
        with st.spinner("Orchestrating MD → module agents → synthesis…"):
            result: OrchestrationResult = run_sync(
                request,
                generate_podcast=gen_pod,
                podcast_module=None if pod_module == "(auto)" else pod_module,
                event_bus=bus,
            )
        progress.progress(100, text=f"Completed in {result.elapsed:.1f}s")
        st.session_state.orchestration_result = result

    # ---- Render the most recent run (if any) ------------------------------
    result: Optional[OrchestrationResult] = st.session_state.orchestration_result
    if result is None:
        st.markdown(
            "<div class='panel'>"
            "<span class='small-muted'>No run yet. Submit a request above to begin.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown("### Orchestration trace")
    _render_event_log(result.events)

    st.markdown("### Delegation plan")
    if result.plan:
        cols = st.columns(len(result.plan.agents) or 1)
        for i, agent in enumerate(result.plan.agents):
            with cols[i % len(cols)]:
                st.markdown(
                    f"<div class='agent-tile'>"
                    f"<h4>{agent}</h4>"
                    f"<p>{result.plan.queries.get(agent, '')[:200]}</p>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        with st.expander("Rationale"):
            st.write(result.plan.rationale or "—")

    st.markdown("### Module responses")
    for resp in result.module_responses:
        with st.expander(
            f"{resp.actor} · {resp.elapsed:.2f}s · {len(resp.citations)} citation(s)"
        ):
            st.markdown(resp.text)
            if resp.citations:
                st.markdown("**Citations**")
                st.json(resp.citations)

    st.markdown("### Final deliverable")
    st.markdown(
        "<div class='panel'>" + (result.final_markdown or "_(empty)_") + "</div>",
        unsafe_allow_html=True,
    )
    st.download_button(
        "Download Markdown",
        data=result.final_markdown.encode("utf-8"),
        file_name=f"briefing-{int(time.time())}.md",
        mime="text/markdown",
    )

    if result.podcast and Path(result.podcast.file_path).exists():
        st.markdown("### Briefing podcast")
        st.markdown(f"**{result.podcast.title}**")
        st.audio(str(result.podcast.file_path))
        with open(result.podcast.file_path, "rb") as f:
            st.download_button(
                "Download podcast",
                data=f.read(),
                file_name=Path(result.podcast.file_path).name,
                mime="audio/mpeg",
            )


def _render_event_log(events: List[OrchestratorEvent]):
    if not events:
        st.markdown(
            "<div class='small-muted'>No events recorded.</div>",
            unsafe_allow_html=True,
        )
        return
    rows: List[str] = []
    for e in events:
        ts = time.strftime("%H:%M:%S", time.localtime(e.ts))
        rows.append(
            f"<div class='log-row'>"
            f"<span class='small-muted'>{ts}</span> &nbsp;"
            f"<span class='log-actor'>{e.actor}</span>"
            f"<span class='log-phase'>{e.phase}</span>"
            f"{e.message}"
            f"</div>"
        )
    st.markdown(
        "<div class='panel' style='max-height:320px;overflow:auto'>"
        + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


# =============================================================================
# Main
# =============================================================================
def main():
    render_header()
    tab_cfg, tab_kb, tab_ws = st.tabs(["⚙  Configuration", "📚  Knowledge Base", "🛰  Workspace"])
    with tab_cfg:
        render_configuration_tab()
    with tab_kb:
        render_knowledge_base_tab()
    with tab_ws:
        render_workspace_tab()


if __name__ == "__main__":
    main()
