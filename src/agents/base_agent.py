"""Base agent: standard prompt loading and async query execution."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from ..notebooklm_client import NotebookAnswer, NotebookLMClientWrapper, get_client
from ..utils import load_prompt

# Optional: Gemini for the MD planner / synthesis. Falls back to a deterministic
# template if the SDK isn't configured.
_GENAI_AVAILABLE = False
try:
    from google import genai                              # type: ignore
    _GENAI_AVAILABLE = True
except Exception:                                         # pragma: no cover
    pass


@dataclass
class AgentResponse:
    actor: str
    text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    notebook_id: Optional[str] = None
    elapsed: float = 0.0
    raw: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor": self.actor,
            "text": self.text,
            "citations": self.citations,
            "notebook_id": self.notebook_id,
            "elapsed": self.elapsed,
        }


class BaseAgent:
    """Common scaffolding for any agent in the team."""

    #: short module key — "MD", "MM", "SD", ...
    key: str = "BASE"
    #: human-readable name shown in the UI
    display_name: str = "Base Agent"

    def __init__(
        self,
        client: Optional[NotebookLMClientWrapper] = None,
        model: str = "gemini-2.5-flash",
    ) -> None:
        self.client = client or get_client()
        self.system_prompt = load_prompt(self.key)
        self.model = model
        self._genai_client: Any = None
        if _GENAI_AVAILABLE and os.environ.get("GOOGLE_API_KEY"):
            try:
                self._genai_client = genai.Client(
                    api_key=os.environ["GOOGLE_API_KEY"]
                )
            except Exception as exc:                      # pragma: no cover
                logger.warning(f"genai client init failed: {exc!r}")

    # ----------------------------- helpers ---------------------------------
    async def _llm_complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
    ) -> str:
        """Plain LLM completion via google-genai. Used by the MD for
        planning / synthesis. Module agents go through NotebookLM RAG instead.
        """
        system = system or self.system_prompt
        if self._genai_client is None:
            # Deterministic fallback for offline development
            return self._offline_fallback(prompt, system=system)

        def _call() -> str:
            res = self._genai_client.models.generate_content(
                model=self.model,
                contents=[
                    {"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}
                ],
            )
            return getattr(res, "text", None) or str(res)

        return await asyncio.to_thread(_call)

    def _offline_fallback(self, prompt: str, *, system: str) -> str:
        """Used only when no LLM API key is configured.

        For the MD this still produces a valid delegation block based on
        keyword heuristics, so the end-to-end flow runs.
        """
        return f"OFFLINE_FALLBACK: {self.key} received prompt of length {len(prompt)}"


__all__ = ["BaseAgent", "AgentResponse"]
