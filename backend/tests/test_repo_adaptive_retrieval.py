from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "backend"))

from app.retrieval.context_bundle import build_context_bundle  # noqa: E402
from app.retrieval.repo_profiler import profile_repository  # noqa: E402
from app.retrieval.symbol_graph import build_symbol_graph  # noqa: E402
from app.retrieval.validation_planner import build_validation_plan  # noqa: E402


def test_repo_profiler_detects_python_repo():
    repo_root = ROOT
    profile = profile_repository(repo_root, repo_state={"commit_sha": None, "dirty": True})

    assert profile["primary_language"] == "python"
    assert profile["services"]
    assert "pytest" in profile["frameworks"]


def test_validation_plan_prefers_related_tests():
    repo_root = ROOT
    repo_state = {"commit_sha": None, "dirty": True}
    profile = profile_repository(repo_root, repo_state=repo_state)
    graph = build_symbol_graph(repo_root, profile, repo_state=repo_state)

    plan = build_validation_plan(
        repo_root,
        profile,
        graph,
        ticket={"summary": "Discount applied twice during checkout", "description": "Order totals are wrong"},
        terms=["discount", "checkout", "orders", "payments"],
        likely_files=["tests/test_orders.py", "tests/test_payments.py"],
        preferred_service="python",
        failure_signals={},
    )

    selected = plan.get("selected_test_paths") or []
    assert any(path.endswith("tests/test_orders.py") for path in selected)
    assert any(path.endswith("tests/test_payments.py") for path in selected)


def test_context_bundle_includes_profile_and_validation_plan():
    repo_root = ROOT
    bundle = build_context_bundle(
        repo_root=repo_root,
        ticket={"summary": "Checkout total wrong after discount", "description": "Discount appears twice"},
        terms=["discount", "checkout", "orders"],
        likely_files=["tests/test_orders.py"],
        service="python",
        bug_type="logic_error",
        root_cause_hint="Discount logic may be applied twice",
        failure_signals={},
        retry_context=None,
        requested_commit_sha=None,
        mcp_candidate_paths=[],
    )

    assert bundle.get("repo_profile")
    assert bundle.get("validation_plan")
    assert bundle.get("ranked_files")
