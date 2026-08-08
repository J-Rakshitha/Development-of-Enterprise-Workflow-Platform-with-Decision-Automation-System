"""Built-in workflow templates — Milestone 4 orchestration."""
import json

WORKFLOW_TEMPLATES: dict[str, dict] = {
    "dev-conflict-resolution": {
        "name": "Dev Conflict Resolution",
        "description": (
            "Repository discovery → semantic review → AI suggestion → HITL approval → commit record. "
            "Pauses at human review gate until the signed-in user approves."
        ),
        "steps": [
            {"id": "validate_conflict", "agent": "Conflict Prediction Agent", "module": "dev_collab"},
            {"id": "semantic_review", "agent": "Semantic Analysis Agent", "module": "dev_collab"},
            {"id": "ai_suggestion", "agent": "Resolution Suggestion Agent", "module": "dev_collab"},
            {"id": "hitl_gate", "agent": "Human Reviewer", "module": "dev_collab", "requires_hitl": True},
            {"id": "commit_record", "agent": "Coordinator Agent", "module": "dev_collab"},
            {"id": "complete", "agent": "Workflow Orchestrator", "module": "system"},
        ],
    },
    "incident-response": {
        "name": "Incident Response Pipeline",
        "description": (
            "Monitoring anomaly → root cause → severity → tool execution → escalation → "
            "coordinator link → team notification."
        ),
        "steps": [
            {"id": "detect_anomaly", "agent": "Monitoring Agent", "module": "aiops"},
            {"id": "root_cause", "agent": "Root Cause Agent", "module": "aiops"},
            {"id": "severity_classify", "agent": "Severity Agent", "module": "aiops"},
            {"id": "tool_execute", "agent": "Tool Executor Agent", "module": "aiops"},
            {"id": "escalation", "agent": "Escalation Agent", "module": "aiops"},
            {"id": "coordinator_link", "agent": "Coordinator Agent", "module": "aiops"},
            {"id": "notify_team", "agent": "Notification Agent", "module": "aiops"},
            {"id": "complete", "agent": "Workflow Orchestrator", "module": "system"},
        ],
    },
    "full-sdlc-bridge": {
        "name": "Full SDLC Bridge (Dev → Ops)",
        "description": (
            "End-to-end: conflict resolution with HITL, then cross-module correlation linking "
            "the resolved commit to any open production incident."
        ),
        "steps": [
            {"id": "validate_conflict", "agent": "Conflict Prediction Agent", "module": "dev_collab"},
            {"id": "ai_suggestion", "agent": "Resolution Suggestion Agent", "module": "dev_collab"},
            {"id": "hitl_gate", "agent": "Human Reviewer", "module": "dev_collab", "requires_hitl": True},
            {"id": "commit_record", "agent": "Coordinator Agent", "module": "dev_collab"},
            {"id": "incident_correlation", "agent": "Coordinator Agent", "module": "aiops"},
            {"id": "complete", "agent": "Workflow Orchestrator", "module": "system"},
        ],
    },
}


def template_steps(template_key: str) -> list[dict]:
    tpl = WORKFLOW_TEMPLATES.get(template_key)
    if not tpl:
        raise ValueError(f"Unknown workflow template: {template_key}")
    return tpl["steps"]


def template_to_json(template_key: str) -> str:
    return json.dumps(template_steps(template_key))
