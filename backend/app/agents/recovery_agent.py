from app.agents.state import AgentState


LLM_SWITCH_FAILURE_TYPES = {
    "rate_limit",
    "timeout",
    "provider_unavailable",
    "llm_generation_failure",
    "provider_http_error",
    "connection_error",
}


def _append_trace(state: AgentState, message: str) -> list[str]:
    trace = list(state.get("decision_trace") or [])
    trace.append(message)
    return trace


def recovery_agent_node(state: AgentState) -> AgentState:
    status = str(state.get("status") or "").strip().lower()
    sandbox = state.get("sandbox_result") or {}
    failure_type = str(state.get("failure_type") or "").strip().lower()

    if status == "sandbox_passed":
        return {
            "recovery_result": {
                "decision": "finalize",
                "reason": "Validation passed",
            },
            "decision_trace": _append_trace(state, "recovery_agent -> finalize (validation passed)"),
            "retry_category": "none",
            "error": None,
        }

    if status == "sandbox_failed":
        failed_tests = sandbox.get("failed_tests") or []
        if failed_tests:
            return {
                "recovery_result": {
                    "decision": "retry_fix",
                    "reason": "Selected tests failed after patch",
                    "failed_tests": failed_tests,
                },
                "status": "failed_tests",
                "retry_category": "code",
                "error": state.get("error") or "Selected tests failed after patch",
                "decision_trace": _append_trace(state, "recovery_agent -> retry_fix (failed tests present)"),
            }

        return {
            "recovery_result": {
                "decision": "retry_fix",
                "reason": "Validation failed without explicit failed test list",
            },
            "status": "validation_failed",
            "retry_category": "code",
            "error": state.get("error") or sandbox.get("error") or "Validation failed after patch",
            "decision_trace": _append_trace(state, "recovery_agent -> retry_fix (validation failed)"),
        }

    if failure_type in LLM_SWITCH_FAILURE_TYPES:
        return {
            "recovery_result": {
                "decision": "switch_provider",
                "reason": f"Transient/provider failure detected ({failure_type})",
            },
            "retry_category": "llm",
            "error": state.get("error") or f"Provider failure: {failure_type}",
            "decision_trace": _append_trace(state, f"recovery_agent -> switch_provider ({failure_type})"),
        }

    if status == "sandbox_infra_failed":
        return {
            "recovery_result": {
                "decision": "finalize",
                "reason": "Validation infrastructure failure",
            },
            "retry_category": "infra",
            "error": state.get("error") or sandbox.get("error") or "Validation infrastructure failure",
            "decision_trace": _append_trace(state, "recovery_agent -> finalize (infra failure)"),
        }

    return {
        "recovery_result": {
            "decision": "finalize",
            "reason": "No recovery action required",
        },
        "decision_trace": _append_trace(state, "recovery_agent -> finalize (default path)"),
    }
