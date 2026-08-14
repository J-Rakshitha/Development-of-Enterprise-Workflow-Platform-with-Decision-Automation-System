"""
Rule-based fallback logic.
These functions are passed into HybridAIClient.reason() as `fallback_fn`
so the system keeps working (with slightly less "smart" wording)
even when the LLM API is unreachable.
"""
import random

# Distinct cause templates keyed by dominant live metric (enterprise, not demo copy)
_POOL_CAUSES = (
    "connection pool exhaustion — unreleased connections or slow queries are starving new requests",
    "database connection pool is saturated — acquiring new connections is blocking under load",
)
_ERROR_CAUSES = (
    "elevated error rate from a failing dependency after a recent change",
    "elevated error rate — unhandled exception path cascading after a recent deploy",
)
_LATENCY_CAUSES = (
    "elevated latency under load — requests are queuing behind a slow downstream DB or API",
    "request queue buildup — thread/worker saturation behind a slow dependency",
)

_last_cause_text: str | None = None


def fallback_conflict_suggestion(dev_a: str, dev_b: str, file_path: str, function_name: str) -> str:
    return (
        f"{dev_a} and {dev_b} are both editing '{function_name}' in {file_path}. "
        f"Recommended: {dev_a} should pause and sync with {dev_b} before pushing, "
        f"or split the function into smaller units to avoid overlapping changes."
    )


def _pick_cause(templates: tuple[str, ...]) -> str:
    """Prefer a different sentence than the previous incident when alternatives exist."""
    global _last_cause_text
    options = list(templates)
    if _last_cause_text and len(options) > 1:
        options = [t for t in options if t != _last_cause_text]
    choice = random.choice(options)
    _last_cause_text = choice
    return choice


def _dominant_cause_from_metrics(metrics: dict, error_signature: str) -> str:
    """Pick root-cause wording from the highest live metric, with template variety."""
    pool = float(metrics.get("db_pool_usage_pct") or 0)
    err = float(metrics.get("error_rate_pct") or 0)
    latency = float(metrics.get("response_time_ms") or 0)
    latency_score = min(100.0, latency / 100.0)
    sig = (error_signature or "").lower()

    scores = {
        "pool": pool,
        "error": err,
        "latency": latency_score,
    }
    # Tie-break using error signature hints when present
    if "connection_pool" in sig or "db_pool" in sig:
        scores["pool"] += 0.5
    if "high_error_rate" in sig or "error_rate" in sig:
        scores["error"] += 0.5
    if "high_response_time" in sig or "latency" in sig:
        scores["latency"] += 0.5

    dominant = max(scores, key=scores.get)

    if dominant == "pool":
        return _pick_cause(_POOL_CAUSES)
    if dominant == "error":
        return _pick_cause(_ERROR_CAUSES)
    return _pick_cause(_LATENCY_CAUSES)


def fallback_root_cause(
    service_name: str,
    error_signature: str,
    raw_metrics: dict | None = None,
    triggered_by: str | None = None,
) -> str:
    from datetime import datetime, timezone

    metrics = raw_metrics or {}
    who = (triggered_by or "System").strip() or "System"
    pool = metrics.get("db_pool_usage_pct")
    err = metrics.get("error_rate_pct")
    latency = metrics.get("response_time_ms")
    users = metrics.get("affected_users_pct")
    observed_at = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    explanation = _dominant_cause_from_metrics(metrics, error_signature)

    bits = []
    if err is not None:
        bits.append(f"error_rate {err}%")
    if pool is not None:
        bits.append(f"DB pool {pool}%")
    if latency is not None:
        bits.append(f"latency {latency}ms")
    if users is not None:
        bits.append(f"affected users {users}%")
    metric_clause = f" Live metrics at {observed_at}: {', '.join(bits)}." if bits else f" Observed at {observed_at}."
    return (
        f"[{service_name}] Likely cause: {explanation}.{metric_clause} "
        f"Triggered by {who}."
    )


def fallback_severity(service_name: str, error_rate: float, affected_users_pct: float) -> str:
    if error_rate > 50 or affected_users_pct > 70:
        return "P1"
    if error_rate > 15 or affected_users_pct > 30:
        return "P2"
    return "P3"


def fallback_remediation_action(root_cause_hint: str) -> str:
    hint = root_cause_hint.lower()
    if "connection_pool" in hint or "connection pool" in hint or "pool exhaustion" in hint or "timeout" in hint:
        return "restart_service"
    if "memory" in hint or "cache" in hint:
        return "clear_cache"
    return "notify_oncall_engineer"


def fallback_code_review(
    file_path: str,
    function_name: str | None,
    dev_a: str,
    dev_b: str,
    risk_score: float,
) -> str:
    fn = function_name or "the file"
    tips = []
    if file_path.endswith(".py"):
        tips.append("Use snake_case for functions and add type hints to public APIs.")
    elif file_path.endswith(".js"):
        tips.append("Prefer const/let over var and keep functions under 50 lines.")
    else:
        tips.append("Follow the project's style guide before merging overlapping edits.")

    if risk_score >= 70:
        tips.append(
            f"High overlap risk ({risk_score}%): {dev_a} and {dev_b} should pair-review "
            f"changes in '{fn}' before either pushes."
        )
    else:
        tips.append(f"{dev_a} and {dev_b} should sync on '{fn}' in {file_path} to avoid losing work.")

    tips.append("Add or update unit tests for the modified function.")
    return " ".join(tips)


def fallback_semantic_analysis(
    file_path: str,
    function_name: str | None,
    dev_a: str,
    dev_b: str,
    risk_score: float,
    ast_report: dict,
) -> str:
    fn = function_name or "the file"
    parts = [
        f"{dev_a} and {dev_b} may introduce incompatible logic in '{fn}' ({file_path})."
    ]
    if ast_report.get("signature_changed"):
        parts.append("AST shows signature changes — callers may break after merge.")
    if ast_report.get("complexity_a", 0) > 10 or ast_report.get("complexity_b", 0) > 10:
        parts.append("High cyclomatic complexity increases regression risk.")
    if risk_score >= 60:
        parts.append(f"Semantic risk elevated ({risk_score}%) — require joint review before push.")
    return " ".join(parts)


def fallback_quality_report(metrics: dict) -> str:
    score = metrics.get("quality_score", 50)
    cx = metrics.get("cyclomatic_complexity", 1)
    if score >= 85:
        return f"Quality score {score}/100 — acceptable. Complexity {cx}; maintain test coverage."
    if score >= 65:
        return (
            f"Quality score {score}/100 — moderate. Complexity {cx}; "
            "add docstrings and reduce function length before merge."
        )
    return (
        f"Quality score {score}/100 — needs improvement. Complexity {cx}; "
        "refactor before merging overlapping edits."
    )


def fallback_resolution_strategies(
    dev_a: str,
    dev_b: str,
    file_path: str,
    function_name: str | None,
    sem_risk: float,
    conflict_type: str,
    grade: str,
) -> str:
    fn = function_name or "the target"
    return (
        f"Strategy 1: {dev_a} rebases onto {dev_b}'s branch and resolves {fn} conflicts. "
        f"Strategy 2: split {conflict_type} work — separate PRs for logic vs tests. "
        f"Strategy 3: pair-program given semantic risk {sem_risk}% and grade {grade}."
    )
