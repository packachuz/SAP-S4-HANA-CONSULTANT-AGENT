"""Shared utilities: logging, file handling, prompt loading."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from loguru import logger

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
KB_DIR = DATA_DIR / "knowledge_base"
PODCAST_DIR = DATA_DIR / "podcasts"
LOG_DIR = DATA_DIR / "logs"

for p in (DATA_DIR, KB_DIR, PODCAST_DIR, LOG_DIR):
    p.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level: <7}</level> "
            "<cyan>{name}:{function}:{line}</cyan> | <level>{message}</level>"
        ),
    )
    logger.add(
        LOG_DIR / "orchestrator.log",
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
        enqueue=True,
    )


configure_logging()


# ----------------------------------------------------------------------------
# Prompt loader
# ----------------------------------------------------------------------------
def load_prompt(name: str) -> str:
    """Load a system prompt from config/<name>_prompt.txt."""
    path = CONFIG_DIR / f"{name.lower()}_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


# ----------------------------------------------------------------------------
# Event log for the Streamlit UI
# ----------------------------------------------------------------------------
@dataclass
class OrchestratorEvent:
    """A single step in the orchestration trace, surfaced to the UI."""

    ts: float = field(default_factory=time.time)
    actor: str = "system"            # "MD", "MM", "FI", ...
    phase: str = "info"              # "plan" | "delegate" | "respond" | "synthesize" | "error" | "info"
    message: str = ""
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "actor": self.actor,
            "phase": self.phase,
            "message": self.message,
            "payload": self.payload,
        }


class EventBus:
    """Async fan-out for orchestrator events.

    The orchestrator publishes; the Streamlit UI subscribes (polling
    `drain()` from its render loop is the simplest pattern).
    """

    def __init__(self) -> None:
        self._events: List[OrchestratorEvent] = []
        self._listeners: List[Callable[[OrchestratorEvent], None]] = []
        self._lock = asyncio.Lock()

    def subscribe(self, fn: Callable[[OrchestratorEvent], None]) -> None:
        self._listeners.append(fn)

    async def publish(
        self,
        actor: str,
        phase: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> OrchestratorEvent:
        evt = OrchestratorEvent(actor=actor, phase=phase, message=message, payload=payload)
        async with self._lock:
            self._events.append(evt)
        for fn in self._listeners:
            try:
                fn(evt)
            except Exception as exc:                       # pragma: no cover
                logger.warning(f"event listener failed: {exc}")
        logger.info(f"[{actor}] ({phase}) {message}")
        return evt

    def drain(self) -> List[OrchestratorEvent]:
        out, self._events = self._events, []
        return out

    def snapshot(self) -> List[OrchestratorEvent]:
        return list(self._events)


# ----------------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------------
def extract_json_block(text: str, tag: str = "delegation") -> Optional[Dict[str, Any]]:
    """Extract a ```<tag> ... ``` fenced JSON block from an LLM reply."""
    import re

    pattern = rf"```{tag}\s*(\{{.*?\}})\s*```"
    m = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        # fall back: first {...} that parses
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return None
        try:
            return json.loads(m2.group(0))
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


# ----------------------------------------------------------------------------
# Notebook registry  (module key -> notebookLM notebook id)
# ----------------------------------------------------------------------------
REGISTRY_PATH = DATA_DIR / "notebook_registry.json"


def get_notebook_registry() -> Dict[str, str]:
    return read_json(REGISTRY_PATH, default={}) or {}


def set_notebook_id(module: str, notebook_id: str) -> None:
    reg = get_notebook_registry()
    reg[module.upper()] = notebook_id
    write_json(REGISTRY_PATH, reg)


__all__ = [
    "ROOT",
    "CONFIG_DIR",
    "DATA_DIR",
    "KB_DIR",
    "PODCAST_DIR",
    "LOG_DIR",
    "configure_logging",
    "load_prompt",
    "OrchestratorEvent",
    "EventBus",
    "extract_json_block",
    "write_json",
    "read_json",
    "get_notebook_registry",
    "set_notebook_id",
]
