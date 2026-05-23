"""Main async orchestration: MD -> module agents -> synthesis -> podcast."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .agents import (
    ALL_MODULE_AGENTS,
    AgentResponse,
    DelegationPlan,
    MDAgent,
    ModuleAgent,
)
from .notebooklm_client import NotebookLMClientWrapper, PodcastResult, get_client
from .utils import EventBus, OrchestratorEvent


@dataclass
class OrchestrationResult:
    client_request: str = ""
    plan: Optional[DelegationPlan] = None
    module_responses: List[AgentResponse] = field(default_factory=list)
    final_markdown: str = ""
    podcast: Optional[PodcastResult] = None
    elapsed: float = 0.0
    events: List[OrchestratorEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_request": self.client_request,
            "plan": self.plan.to_dict() if self.plan else None,
            "module_responses": [r.to_dict() for r in self.module_responses],
            "final_markdown": self.final_markdown,
            "podcast": (
                {"file_path": str(self.podcast.file_path), "title": self.podcast.title}
                if self.podcast else None
            ),
            "elapsed": self.elapsed,
            "events": [e.to_dict() for e in self.events],
        }


class Orchestrator:
    """Coordinates the MD and module agents to fulfill a client request."""

    def __init__(
        self,
        client: Optional[NotebookLMClientWrapper] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.client = client or get_client()
        self.bus = event_bus or EventBus()
        self.md = MDAgent(client=self.client)
        self.modules: Dict[str, ModuleAgent] = {
            key: cls(client=self.client) for key, cls in ALL_MODULE_AGENTS.items()
        }

    # ----------------------------- public API -------------------------------
    async def run(
        self,
        client_request: str,
        *,
        generate_podcast: bool = True,
        podcast_module: Optional[str] = None,
    ) -> OrchestrationResult:
        """Full orchestration pipeline."""
        started = time.time()
        result = OrchestrationResult(client_request=client_request)

        await self.bus.publish("MD", "info", "Received client request.",
                               payload={"length": len(client_request)})

        # 1) Plan
        await self.bus.publish("MD", "plan", "Decomposing request into module sub-queries…")
        plan = await self.md.plan(client_request)
        result.plan = plan
        await self.bus.publish(
            "MD", "delegate",
            f"Engaging {len(plan.agents)} agent(s): {', '.join(plan.agents)}",
            payload=plan.to_dict(),
        )

        # 2) Fan out to module agents in parallel
        tasks = [
            self._dispatch(agent_key, plan.queries.get(agent_key, client_request))
            for agent_key in plan.agents
            if agent_key in self.modules
        ]
        if tasks:
            module_responses = await asyncio.gather(*tasks, return_exceptions=True)
            for resp in module_responses:
                if isinstance(resp, Exception):
                    await self.bus.publish(
                        "system", "error",
                        f"Module call failed: {resp!r}",
                    )
                    continue
                result.module_responses.append(resp)
        else:
            await self.bus.publish("MD", "info", "No module agents required.")

        # 3) Synthesize
        await self.bus.publish("MD", "synthesize",
                               "Compiling executive deliverable…")
        final = await self.md.synthesize(client_request, plan, result.module_responses)
        result.final_markdown = final.text
        await self.bus.publish("MD", "respond",
                               f"Final deliverable ready ({len(final.text)} chars).")

        # 4) Optional briefing podcast
        if generate_podcast:
            pm = podcast_module or (plan.agents[0] if plan.agents else "FI")
            await self.bus.publish(
                pm, "info",
                f"Generating Audio Overview for {pm}…",
            )
            try:
                pod = await self.client.generate_podcast(
                    module=pm,
                    focus=client_request,
                    title=f"SAP {pm} — Client Briefing",
                )
                result.podcast = pod
                await self.bus.publish(
                    pm, "respond",
                    f"Podcast saved → {pod.file_path}",
                    payload={"file_path": str(pod.file_path)},
                )
            except Exception as exc:
                await self.bus.publish(
                    "system", "error",
                    f"Podcast generation failed: {exc!r}",
                )

        result.elapsed = time.time() - started
        result.events = self.bus.snapshot()
        await self.bus.publish(
            "system", "info",
            f"Orchestration complete in {result.elapsed:.1f}s",
        )
        return result

    # ----------------------------- internals --------------------------------
    async def _dispatch(self, agent_key: str, sub_query: str) -> AgentResponse:
        agent = self.modules[agent_key]
        await self.bus.publish(agent_key, "delegate",
                               f"Sub-query received ({len(sub_query)} chars).")
        try:
            resp = await agent.query(sub_query)
        except Exception as exc:                            # pragma: no cover
            await self.bus.publish(agent_key, "error", f"{exc!r}")
            raise
        await self.bus.publish(
            agent_key, "respond",
            f"Replied in {resp.elapsed:.2f}s ({len(resp.text)} chars).",
            payload={"citations": len(resp.citations)},
        )
        return resp


# ---------------------------------------------------------------------------
# Sync convenience wrapper for Streamlit
# ---------------------------------------------------------------------------
def run_sync(
    client_request: str,
    *,
    generate_podcast: bool = True,
    podcast_module: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
) -> OrchestrationResult:
    """Sync wrapper — Streamlit runs in a thread, so a fresh loop is fine."""
    orch = Orchestrator(event_bus=event_bus)
    return asyncio.run(
        orch.run(
            client_request,
            generate_podcast=generate_podcast,
            podcast_module=podcast_module,
        )
    )


__all__ = ["Orchestrator", "OrchestrationResult", "run_sync"]
