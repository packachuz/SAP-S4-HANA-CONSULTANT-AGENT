"""Module agents — each bound to a module-specific NotebookLM notebook."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .base_agent import AgentResponse, BaseAgent


class ModuleAgent(BaseAgent):
    """Generic SAP module agent. Subclasses set `key` and `display_name`."""

    key: str = "MODULE"
    display_name: str = "Module"

    async def query(self, sub_query: str) -> AgentResponse:
        """Run a sub-query against the module's NotebookLM notebook."""
        started = time.time()
        answer = await self.client.chat(
            module=self.key,
            query=sub_query,
            system_prompt=self.system_prompt,
        )
        return AgentResponse(
            actor=self.key,
            text=answer.text,
            citations=answer.citations,
            notebook_id=answer.notebook_id,
            elapsed=time.time() - started,
            raw=answer,
        )

    async def ensure_notebook(self) -> str:
        return await self.client.get_or_create_notebook(self.key)


# ---------------------------------------------------------------------------
# Concrete agents
# ---------------------------------------------------------------------------
class MMAgent(ModuleAgent):
    key = "MM"
    display_name = "Materials Management"


class SDAgent(ModuleAgent):
    key = "SD"
    display_name = "Sales & Distribution"


class FIAgent(ModuleAgent):
    key = "FI"
    display_name = "Financial Accounting"


class COAgent(ModuleAgent):
    key = "CO"
    display_name = "Controlling"


class HCMAgent(ModuleAgent):
    key = "HCM"
    display_name = "Human Capital Management"


class ARIBAAgent(ModuleAgent):
    key = "ARIBA"
    display_name = "SAP Ariba"


ALL_MODULE_AGENTS: Dict[str, type[ModuleAgent]] = {
    "MM":    MMAgent,
    "SD":    SDAgent,
    "FI":    FIAgent,
    "CO":    COAgent,
    "HCM":   HCMAgent,
    "ARIBA": ARIBAAgent,
}


__all__ = [
    "ModuleAgent",
    "MMAgent", "SDAgent", "FIAgent", "COAgent", "HCMAgent", "ARIBAAgent",
    "ALL_MODULE_AGENTS",
]
