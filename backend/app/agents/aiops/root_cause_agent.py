"""
Root-Cause Analysis Agent
==========================
Explains WHY an anomaly likely happened from THIS run's live metrics.
Never reuses identical prior text — each trigger gets fresh, suitable wording.
"""
from app.agents.llm.llm_client import HybridAIClient
from app.agents.llm.fallback_rules import fallback_root_cause
from app.agents.llm.prompt_templates import ROOT_CAUSE_PROMPT
from app.agents.coordinator_agent import CoordinatorAgent
from app.agents.memory_agent import MemoryAgent


class RootCauseAgent:

    @staticmethod
    async def analyze(
        db,
        service_name: str,
        error_signature: str,
        raw_metrics: dict,
        triggered_by: str | None = None,
    ) -> dict:
        key_signature = f"{service_name}:{error_signature}"
        who = (triggered_by or "System").strip() or "System"

        def fallback():
            return fallback_root_cause(
                service_name,
                error_signature,
                raw_metrics=raw_metrics,
                triggered_by=who,
            )

        # Card text is always THIS run's live metrics — do not reuse LLM/memory copy
        text = fallback()
        result = await HybridAIClient.reason(prompt=ROOT_CAUSE_PROMPT.format(
            service_name=service_name,
            raw_metrics=raw_metrics,
            error_signature=error_signature,
            triggered_by=who,
            memory_context="",
        ), fallback_fn=fallback)

        await CoordinatorAgent.log_decision(
            db=db,
            agent_name="Root-Cause Analysis Agent",
            module="aiops",
            decision_summary=text,
            used_llm=result.used_llm,
        )

        await MemoryAgent.remember(
            db, category="incident_resolution", key_signature=key_signature, insight=text
        )

        return {"root_cause": text, "used_llm": result.used_llm}
