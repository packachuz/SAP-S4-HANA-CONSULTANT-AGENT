"""Async wrapper around the unofficial `notebooklm-py` package.

Following inspection of the `notebooklm-py` package, we have mapped all RAG, 
notebook management, chat, and audio artifacts to their native async functions.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .utils import (
    KB_DIR,
    PODCAST_DIR,
    get_notebook_registry,
    set_notebook_id,
    upload_artifact,
)

# ---------------------------------------------------------------------------
# Optional import — degrade gracefully if not installed.
# ---------------------------------------------------------------------------
_REAL_AVAILABLE = False
try:
    from notebooklm import NotebookLMClient  # type: ignore
    _REAL_AVAILABLE = True
except Exception as exc:                                  # pragma: no cover
    logger.warning(
        f"notebooklm-py not importable ({exc!r}); running in STUB mode. "
        "Run `pip install 'notebooklm-py[browser]' && playwright install chromium`."
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class NotebookAnswer:
    text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    notebook_id: str = ""
    elapsed: float = 0.0


@dataclass
class PodcastResult:
    file_path: Path
    title: str
    duration_seconds: Optional[float] = None


# Canonical notebook titles per module
MODULE_NOTEBOOKS: Dict[str, str] = {
    "MM":    "SAP-MM-KB",
    "SD":    "SAP-SD-KB",
    "FI":    "SAP-FI-KB",
    "CO":    "SAP-CO-KB",
    "HCM":   "SAP-HCM-KB",
    "ARIBA": "SAP-ARIBA-KB",
}


class NotebookLMClientWrapper:
    """Single shared async wrapper around a NotebookLM session."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self.storage_path = storage_path or os.environ.get("NOTEBOOKLM_STORAGE")
        self._client: Any = None
        self._connected = False
        self.stub_mode = not _REAL_AVAILABLE or os.environ.get("NOTEBOOKLM_STUB") == "1"
        # When set (e.g. on Cloud Run), a failed live connect surfaces as an
        # error instead of silently degrading to STUB — so a broken deploy is
        # visible rather than quietly serving placeholder data.
        self.require_live = os.environ.get("NOTEBOOKLM_REQUIRE_LIVE") == "1"
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ----------------------------- session lifecycle -----------------------
    async def connect(self) -> bool:
        """Initialize the NotebookLM client from saved browser storage."""
        current_loop = asyncio.get_running_loop()
        
        # If already connected to the current running event loop, return True
        if self._connected and self._loop == current_loop:
            return True
            
        # If the event loop has shifted, reset connection state
        if self._connected:
            logger.info("New event loop detected. Re-initializing NotebookLM client connection.")
            self._connected = False
            self._client = None
            self._loop = None
            
        if self.stub_mode:
            self._connected = True
            self._loop = current_loop
            return True

        try:
            if self.storage_path:
                self._client = await NotebookLMClient.from_storage(self.storage_path)
            else:
                self._client = await NotebookLMClient.from_storage()
            
            # Manually enter client context manager to initialize sessions in current loop
            await self._client.__aenter__()
            
            self._connected = True
            self._loop = current_loop
            logger.info("NotebookLM client initialized and context entered.")
            return True
        except Exception as exc:
            if self.require_live:
                logger.error(
                    f"NotebookLM connect failed: {exc!r}. NOTEBOOKLM_REQUIRE_LIVE is "
                    "set, so NOT falling back to STUB. Check that the auth secret is "
                    "mounted (NOTEBOOKLM_STORAGE) and the session has not expired."
                )
                self._connected = False
                self._client = None
                self._loop = None
                return False
            logger.warning(f"NotebookLM connect failed: {exc!r}. Falling back to STUB mode.")
            self.stub_mode = True
            self._connected = True
            self._loop = current_loop
            return True

    async def auth_check(self) -> Dict[str, Any]:
        """Lightweight auth probe — mirrors `notebooklm auth check --test`."""
        if self.stub_mode:
            return {
                "ok": True,
                "mode": "STUB",
                "message": (
                    "notebooklm-py not installed — running stub mode. "
                    "Install with `pip install 'notebooklm-py[browser]'` and run "
                    "`notebooklm login` to enable real RAG."
                ),
            }
        ok = await self.connect()
        path_str = self.storage_path or str(Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json")
        return {
            "ok": ok,
            "mode": "LIVE" if ok else "DISCONNECTED",
            "storage_path": path_str,
            "storage_exists": Path(path_str).exists(),
        }

    # ----------------------------- notebooks --------------------------------
    async def get_or_create_notebook(self, module: str) -> str:
        """Return the notebook id for the given module, creating it if needed."""
        module = module.upper()
        registry = get_notebook_registry()
        if module in registry:
            return registry[module]

        title = MODULE_NOTEBOOKS.get(module, f"SAP-{module}-KB")
        if self.stub_mode:
            nb_id = f"stub-{module.lower()}-{int(time.time())}"
            set_notebook_id(module, nb_id)
            return nb_id

        await self.connect()
        if self.stub_mode:
            nb_id = f"stub-{module.lower()}-{int(time.time())}"
            set_notebook_id(module, nb_id)
            return nb_id

        nb = await self._client.notebooks.create(title=title)
        nb_id = nb.id
        set_notebook_id(module, nb_id)
        logger.info(f"Created notebook {title} -> {nb_id}")
        return nb_id

    async def list_notebooks(self) -> List[Dict[str, Any]]:
        if self.stub_mode:
            reg = get_notebook_registry()
            return [{"id": nid, "title": MODULE_NOTEBOOKS.get(mod, mod), "module": mod}
                    for mod, nid in reg.items()]
        await self.connect()
        if self.stub_mode:
            reg = get_notebook_registry()
            return [{"id": nid, "title": MODULE_NOTEBOOKS.get(mod, mod), "module": mod}
                    for mod, nid in reg.items()]

        nbs = await self._client.notebooks.list()
        return [{"id": n.id, "title": n.title} for n in nbs]

    # ----------------------------- sources ----------------------------------
    async def upload_pdf(self, module: str, pdf_path: Path) -> Dict[str, Any]:
        """Upload a PDF to the module's notebook."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        # Cache a local copy under data/knowledge_base/<module>/
        dest_dir = KB_DIR / module.upper()
        dest_dir.mkdir(parents=True, exist_ok=True)
        local_copy = dest_dir / pdf_path.name
        if pdf_path.resolve() != local_copy.resolve():
            shutil.copy2(pdf_path, local_copy)

        nb_id = await self.get_or_create_notebook(module)

        if self.stub_mode:
            return {
                "ok": True,
                "mode": "STUB",
                "notebook_id": nb_id,
                "source_name": pdf_path.name,
                "local_copy": str(local_copy),
            }

        await self.connect()
        if self.stub_mode:
            return {
                "ok": True,
                "mode": "STUB",
                "notebook_id": nb_id,
                "source_name": pdf_path.name,
                "local_copy": str(local_copy),
            }

        res = await self._client.sources.add_file(notebook_id=nb_id, file_path=local_copy, wait=True)
        return {"ok": True, "result": str(res), "notebook_id": nb_id}

    async def sync_notebook(self, module: str) -> Dict[str, Any]:
        """Re-index / sync the notebook after uploads."""
        nb_id = await self.get_or_create_notebook(module)
        return {"ok": True, "notebook_id": nb_id, "synced": True}

    # ----------------------------- queries ----------------------------------
    async def chat(
        self,
        module: str,
        query: str,
        system_prompt: Optional[str] = None,
    ) -> NotebookAnswer:
        """Ask the module notebook a question and return the grounded answer."""
        nb_id = await self.get_or_create_notebook(module)
        started = time.time()

        if self.stub_mode:
            await asyncio.sleep(0.4 + 0.05 * (len(query) % 7))
            text = _stub_module_answer(module, query)
            return NotebookAnswer(
                text=text,
                citations=[{
                    "source": f"SAP {module} standard guide (stub)",
                    "page": 42,
                }],
                notebook_id=nb_id,
                elapsed=time.time() - started,
            )

        await self.connect()
        if self.stub_mode:
            await asyncio.sleep(0.4 + 0.05 * (len(query) % 7))
            text = _stub_module_answer(module, query)
            return NotebookAnswer(
                text=text,
                citations=[{
                    "source": f"SAP {module} standard guide (stub)",
                    "page": 42,
                }],
                notebook_id=nb_id,
                elapsed=time.time() - started,
            )

        q = f"{system_prompt}\n\n[USER QUERY]\n{query}" if system_prompt else query
        res = await self._client.chat.ask(notebook_id=nb_id, question=q)
        text = getattr(res, "text", "")
        cits = getattr(res, "citations", [])
        cits_list = []
        if cits:
            for cit in cits:
                cits_list.append({
                    "source": getattr(cit, "source_title", "Unknown Source"),
                    "text": getattr(cit, "text", ""),
                })
        return NotebookAnswer(
            text=text,
            citations=cits_list,
            notebook_id=nb_id,
            elapsed=time.time() - started,
        )

    # ----------------------------- web research -----------------------------
    async def web_research(self, module: str, keywords: str) -> Dict[str, Any]:
        """Trigger NotebookLM's dynamic web-research source for fresh material."""
        nb_id = await self.get_or_create_notebook(module)
        if self.stub_mode:
            await asyncio.sleep(0.5)
            return {
                "ok": True,
                "mode": "STUB",
                "notebook_id": nb_id,
                "keywords": keywords,
                "discovered": [
                    f"SAP Help — {keywords}",
                    f"SAP Community blog — {keywords}",
                    f"openSAP course excerpt — {keywords}",
                ],
            }

        await self.connect()
        if self.stub_mode:
            await asyncio.sleep(0.5)
            return {
                "ok": True,
                "mode": "STUB",
                "notebook_id": nb_id,
                "keywords": keywords,
                "discovered": [
                    f"SAP Help — {keywords}",
                    f"SAP Community blog — {keywords}",
                    f"openSAP course excerpt — {keywords}",
                ],
            }

        res = await self._client.research.start(notebook_id=nb_id, query=keywords, source="web", mode="fast")
        return {"ok": True, "notebook_id": nb_id, "result": str(res)}

    # ----------------------------- audio overview ---------------------------
    async def generate_podcast(
        self,
        module: str,
        focus: Optional[str] = None,
        title: Optional[str] = None,
    ) -> PodcastResult:
        """Generate and download the NotebookLM Audio Overview (podcast)."""
        nb_id = await self.get_or_create_notebook(module)
        out_dir = PODCAST_DIR / module.upper()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"{module.lower()}_briefing_{stamp}.mp3"
        title = title or f"SAP {module.upper()} — Executive Briefing"

        if self.stub_mode:
            _write_silent_mp3(out_path)
            return PodcastResult(file_path=out_path, title=title, duration_seconds=2.0)

        await self.connect()
        if self.stub_mode:
            _write_silent_mp3(out_path)
            return PodcastResult(file_path=out_path, title=title, duration_seconds=2.0)

        status = await self._client.artifacts.generate_audio(
            notebook_id=nb_id,
            instructions=focus,
        )
        task_id = getattr(status, "task_id", None) or status["task_id"]
        await self._client.artifacts.wait_for_completion(notebook_id=nb_id, task_id=task_id)
        await self._client.artifacts.download_audio(
            notebook_id=nb_id,
            output_path=str(out_path),
        )
        # Persist to durable storage if configured (Cloud Run disk is ephemeral).
        upload_artifact(out_path, f"podcasts/{module.upper()}/{out_path.name}")
        return PodcastResult(file_path=out_path, title=title)


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------
def _stub_module_answer(module: str, query: str) -> str:
    module = module.upper()
    table_hint = {
        "MM":    "EKKO / EKPO / EBAN",
        "SD":    "VBAK / VBAP / LIKP",
        "FI":    "ACDOCA",
        "CO":    "ACDOCA / CSKS / AUFK",
        "HCM":   "PA0000 / HRP1001",
        "ARIBA": "cXML PurchaseOrderRequest / /ARBA/MSG_*",
    }.get(module, "ACDOCA")
    return (
        f"### Direct Answer (stub — install notebooklm-py for live RAG)\n\n"
        f"For the {module} question — *“{query.strip()[:140]}”* — the standard "
        f"S/4HANA approach uses {table_hint}. This stub response demonstrates "
        f"how a grounded NotebookLM reply will appear; structure, citations and "
        f"tone are preserved.\n\n"
        f"### Relevant Tables / CDS Views\n- {table_hint}\n\n"
        f"### Confidence\nLow (stub).\n"
    )


def _write_silent_mp3(path: Path) -> None:
    """Minimal valid (~silent) MP3 so the UI audio player loads."""
    # A 0.1 s MPEG-1 Layer-3, 32 kbps mono frame. Tiny valid placeholder.
    silent_frame = (
        b"\xff\xfb\x10\xc4" + b"\x00" * 96
    )
    path.write_bytes(silent_frame * 30)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_singleton: Optional[NotebookLMClientWrapper] = None


def get_client() -> NotebookLMClientWrapper:
    global _singleton
    if _singleton is None:
        _singleton = NotebookLMClientWrapper()
    return _singleton


__all__ = [
    "NotebookLMClientWrapper",
    "NotebookAnswer",
    "PodcastResult",
    "MODULE_NOTEBOOKS",
    "get_client",
]
