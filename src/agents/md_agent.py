"""Managing Director agent: plans delegation and synthesizes results."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from ..utils import extract_json_block
from .base_agent import AgentResponse, BaseAgent


@dataclass
class DelegationPlan:
    agents: List[str] = field(default_factory=list)
    queries: Dict[str, str] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"agents": self.agents, "queries": self.queries, "rationale": self.rationale}


# Heuristic keyword map for the offline fallback planner
_MODULE_KEYWORDS: Dict[str, List[str]] = {
    "MM":    ["procure", "purchase order", "po ", "pr ", "vendor", "material master",
              "inventory", "goods receipt", "mrp", "miro", "ekko", "ekpo"],
    "SD":    ["sales order", "billing", "delivery", "pricing", "vbak", "vbap",
              "order-to-cash", "o2c", "shipment", "vf01", "credit management"],
    "FI":    ["gl ", "general ledger", "journal", "accounts payable", "ap ",
              "accounts receivable", "ar ", "asset accounting", "acdoca",
              "tax", "close", "ledger", "intercompany"],
    "CO":    ["cost center", "controlling", "internal order", "wbs", "co-pa",
              "margin analysis", "material ledger", "assessment", "settlement",
              "profit center"],
    "HCM":   ["payroll", "employee", "hr ", "hcm", "successfactors", "infotype",
              "personnel", "time management", "ec ", "ecp"],
    "ARIBA": ["ariba", "sourcing", "supplier network", "rfx", "e-auction",
              "guided buying", "slp", "ariba network", "cig"],
}


class MDAgent(BaseAgent):
    key = "MD"
    display_name = "Managing Director"

    async def plan(self, client_request: str) -> DelegationPlan:
        """Decide which module agents to engage and craft sub-queries."""
        prompt = (
            "CLIENT REQUEST\n--------------\n"
            f"{client_request}\n\n"
            "Decide which subset of agents (MM, SD, FI, CO, HCM, ARIBA) to engage. "
            "Produce ONLY a fenced ```delegation``` JSON block with keys "
            "`agents`, `queries`, `rationale` — nothing else."
        )
        reply = await self._llm_complete(prompt)

        if reply.startswith("OFFLINE_FALLBACK"):
            plan = self._heuristic_plan(client_request)
        else:
            data = extract_json_block(reply, tag="delegation") or {}
            plan = DelegationPlan(
                agents=[a.upper() for a in data.get("agents", []) if a],
                queries={k.upper(): v for k, v in (data.get("queries") or {}).items()},
                rationale=str(data.get("rationale", "")),
            )
            if not plan.agents:
                logger.warning("MD planner returned empty plan; using heuristic.")
                plan = self._heuristic_plan(client_request)

        # Defensive: ensure every engaged agent has a query
        for agent in plan.agents:
            plan.queries.setdefault(agent, client_request)
        return plan

    async def synthesize(
        self,
        client_request: str,
        plan: DelegationPlan,
        module_responses: List[AgentResponse],
    ) -> AgentResponse:
        """Compile module responses into the final executive deliverable."""
        started = time.time()
        bundle = "\n\n".join(
            f"### Response from {r.actor}\n\n{r.text}"
            for r in module_responses
        ) or "_(no module responses)_"

        prompt = (
            "CLIENT REQUEST\n--------------\n"
            f"{client_request}\n\n"
            "DELEGATION PLAN\n---------------\n"
            f"{json.dumps(plan.to_dict(), indent=2)}\n\n"
            "MODULE RESPONSES\n----------------\n"
            f"{bundle}\n\n"
            "Now produce the final executive deliverable. Output ONLY Markdown, "
            "no delegation block."
        )
        reply = await self._llm_complete(prompt)
        if reply.startswith("OFFLINE_FALLBACK"):
            reply = self._offline_synthesis(client_request, plan, module_responses)
        return AgentResponse(
            actor="MD",
            text=reply,
            elapsed=time.time() - started,
        )

    # ----------------------------- offline fallbacks ------------------------
    def _heuristic_plan(self, client_request: str) -> DelegationPlan:
        text = client_request.lower()
        agents: List[str] = []
        for module, kws in _MODULE_KEYWORDS.items():
            if any(kw in text for kw in kws):
                agents.append(module)
        if not agents:
            # Default fan-out for unanchored requests
            agents = ["MM", "FI"]
        queries = {a: client_request for a in agents}
        return DelegationPlan(
            agents=agents,
            queries=queries,
            rationale="Heuristic keyword match (offline planner).",
        )

    def _offline_synthesis(
        self,
        client_request: str,
        plan: DelegationPlan,
        module_responses: List[AgentResponse],
    ) -> str:
        lines: List[str] = []
        lines.append("# Executive Briefing\n")
        lines.append("> _Offline synthesis — set `GOOGLE_API_KEY` for full LLM synthesis._\n")
        lines.append("## Executive Summary\n")
        for agent in plan.agents:
            lines.append(f"- **{agent}** engaged: {plan.queries.get(agent, '')[:120]}…")
        lines.append("\n## Process Impact\n")
        lines.append(
            "Cross-module integration is required across "
            + ", ".join(plan.agents) + "."
        )
        lines.append("\n## Module Findings\n")
        for r in module_responses:
            lines.append(f"### {r.actor}\n\n{r.text}\n")
        lines.append("\n## Recommended Next Steps\n")
        lines.append("1. Validate the assumptions in each module section above.")
        lines.append("2. Confirm scope with the client sponsor.")
        lines.append("3. Schedule a process-design workshop covering the modules listed.")
        lines.append("\n## Open Questions for the Client\n")
        lines.append("- Are there localization or industry-specific requirements not yet captured?")
        lines.append("- What is the target go-live window?")
        return "\n".join(lines)


__all__ = ["MDAgent", "DelegationPlan"]
