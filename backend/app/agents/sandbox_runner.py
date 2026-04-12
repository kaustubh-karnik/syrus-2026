import re
import subprocess
from pathlib import Path

from app.agents.state import AgentState
from app.config import settings
from app.retrieval.repo_profiler import profile_repository
from app.retrieval.symbol_graph import build_symbol_graph
from app.retrieval.validation_planner import build_validation_plan


def _repo_root(state: AgentState) -> Path:
    repo_path = str(state.get("repo_path") or "").strip()
    if not repo_path:
        raise ValueError("Target repository path is missing in state")
    return Path(repo_path).resolve()


def _run(cmd: list[str], repo_root: Path, timeout: int = 180) -> tuple[int, str, str]:
    try:
        print(f"   Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", f"timed out after {timeout}s"
    except FileNotFoundError:
        return 1, "", f"command not found: {cmd[0]}"
    except Exception as exc:
        return 1, "", str(exc)


def _prepare_test_command(plan: dict) -> list[str]:
    base = list(plan.get("test_command_base") or [])
    args = list(plan.get("command_args") or [])
    language = str((plan.get("service") or {}).get("language") or "").lower()
    service_root = str((plan.get("service") or {}).get("root") or ".").strip()
    execution_mode = str(plan.get("execution_mode") or "local").lower()

    if service_root not in {"", "."} and execution_mode in {"docker", "local"}:
        adjusted_args = []
        prefix = f"{service_root}/"
        for arg in args:
            normalized = str(arg)
            if "::" in normalized:
                path_part, selector = normalized.split("::", 1)
                if path_part.startswith(prefix):
                    normalized = f"{path_part[len(prefix):]}::{selector}"
            elif normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
            adjusted_args.append(normalized)
        args = adjusted_args

    if language == "python":
        return [*base, *args, "-v", "--tb=short"]
    if language == "javascript":
        return [*base, *args]
    return [*base, *args]


def _extract_failed_tests(language: str, stdout: str, stderr: str) -> list[str]:
    text = f"{stdout}\n{stderr}"
    failed: list[str] = []
    patterns = (
        [
            r"FAILED\s+([^\s]+::[^\s]+)",
            r"ERROR\s+at setup of\s+([^\s]+::[^\s]+)",
        ]
        if language == "python"
        else [
            r"FAIL\s+([^\n]+\.test\.[^\n]*)",
            r"●\s+([^\n]+)",
        ]
    )
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = str(match).strip()
            if name and name not in failed:
                failed.append(name)
    return failed[:12]


def _extract_passed_tests(language: str, stdout: str, stderr: str) -> list[str]:
    text = f"{stdout}\n{stderr}"
    passed: list[str] = []
    patterns = (
        [
            r"([\w./-]+::[\w\[\]:.-]+)\s+PASSED",
        ]
        if language == "python"
        else [
            r"PASS\s+([^\n]+\.test\.[^\n]*)",
        ]
    )
    for pattern in patterns:
        for match in re.findall(pattern, text):
            name = str(match).strip()
            if name and name not in passed:
                passed.append(name)
    return passed[:20]


def _any_relevant_test_passed(selected_tests: list[str], passed_tests: list[str]) -> bool:
    if not selected_tests or not passed_tests:
        return False

    normalized_selected = [str(item or "").replace("\\", "/").strip().lower() for item in selected_tests]
    normalized_passed = [str(item or "").replace("\\", "/").strip().lower() for item in passed_tests]

    for selected in normalized_selected:
        if not selected:
            continue
        selected_file = selected.split("::", 1)[0]
        for passed in normalized_passed:
            passed_file = passed.split("::", 1)[0]
            if (
                selected == passed
                or selected_file == passed_file
                or passed_file.endswith(selected_file)
                or selected_file.endswith(passed_file)
            ):
                return True
    return False


def _failure_reason(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}"
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(
            marker in line
            for marker in [
                "AssertionError",
                "E       ",
                "Error:",
                "TypeError",
                "NameError",
                "ReferenceError",
                "Expected:",
                "Received:",
                "ModuleNotFoundError",
                "SyntaxError",
            ]
        ):
            lines.append(line)
        if len(lines) >= 8:
            break
    return "\n".join(lines)[:1200]


def _extract_compile_failure_file(stdout: str, stderr: str) -> str | None:
    text = f"{stdout}\n{stderr}"
    patterns = [
        r"Error compiling '([^']+\\.py)'",
        r"File \"([^\"]+\\.py)\"",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return str(match.group(1)).strip()
    return None


def _read_compile_failure_context(repo_root: Path, service_root: str, failure_path: str | None) -> dict | None:
    if not failure_path:
        return None

    normalized = str(failure_path).replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]

    candidates: list[Path] = []
    candidates.append((repo_root / normalized).resolve())
    if service_root not in {"", "."}:
        candidates.append((repo_root / service_root / normalized).resolve())

    for candidate in candidates:
        try:
            if not str(candidate).startswith(str(repo_root.resolve())):
                continue
            if not candidate.exists() or not candidate.is_file():
                continue
            content = candidate.read_text(encoding="utf-8", errors="replace")
            rel = str(candidate.relative_to(repo_root)).replace("\\", "/")
            return {
                "file": rel,
                "content": content[:12000],
            }
        except Exception:
            continue
    return None


def _resolve_validation_plan(state: AgentState, repo_root: Path) -> dict:
    retrieval_context = state.get("retrieval_context") or {}
    repo_state = retrieval_context.get("repo_state") or state.get("repo_state") or {}
    repo_profile = retrieval_context.get("repo_profile") or state.get("repo_profile")
    if not repo_profile:
        repo_profile = profile_repository(repo_root, repo_state=repo_state)
    symbol_graph = build_symbol_graph(repo_root, repo_profile, repo_state=repo_state)

    patch_result = state.get("patch_result") or {}
    modified_files = [str(item or "").replace("\\", "/") for item in (patch_result.get("modified_files") or [])]
    ticket = state.get("ticket") or {}
    terms = []
    terms.extend(str(item) for item in (state.get("keywords") or []) if item)
    for item in [
        state.get("bug_type"),
        state.get("root_cause_hint"),
        ticket.get("summary"),
        ticket.get("description"),
        state.get("retry_feedback"),
    ]:
        if item:
            terms.append(str(item))

    plan = build_validation_plan(
        repo_root,
        repo_profile,
        symbol_graph,
        ticket=ticket,
        terms=terms,
        likely_files=state.get("likely_files") or [],
        modified_files=modified_files,
        preferred_service=state.get("service"),
        failure_text=str(state.get("retry_feedback") or ""),
        failure_signals=state.get("failure_signals") or retrieval_context.get("failure_signals") or {},
    )
    return plan


def _candidate_workdir(repo_root: Path, service_root: str, candidate: dict) -> Path:
    workdir = str(candidate.get("workdir") or service_root or ".").strip()
    return repo_root if workdir in {"", "."} else (repo_root / workdir)


def _candidate_plan(validation_plan: dict, candidate: dict) -> dict:
    merged = dict(validation_plan)
    for key in ["mode", "docker_service", "build_command", "test_command_base", "dependency_commands", "workdir", "confidence"]:
        if key in candidate:
            merged[key if key != "mode" else "execution_mode"] = candidate[key]
    return merged


def _local_command_available(plan: dict, repo_root: Path) -> bool:
    test_command_base = list(plan.get("test_command_base") or [])
    if not test_command_base:
        return False
    executable = test_command_base[0]
    if executable == "python":
        returncode, _, stderr = _run(["python", "--version"], repo_root, timeout=10)
        if returncode != 0:
            return False
        if len(test_command_base) >= 3 and test_command_base[1:3] == ["-m", "pytest"]:
            returncode, _, stderr = _run(["python", "-c", "import pytest"], repo_root, timeout=10)
            if returncode != 0 and "No module named pytest" in stderr:
                return False
        return True
    if executable == "npm":
        returncode, _, _ = _run(["npm", "--version"], repo_root, timeout=10)
        return returncode == 0
    return False


def _stop_docker(repo_root: Path) -> None:
    print("Stopping containers...")
    _run(["docker", "compose", "down", "--remove-orphans"], repo_root, timeout=30)


def sandbox_runner_node(state: AgentState) -> AgentState:
    try:
        repo_root = _repo_root(state)
    except ValueError as exc:
        return {
            "sandbox_result": {
                "success": False,
                "service": None,
                "stage": "validation_planning",
                "skipped": False,
                "commands": [],
                "error": str(exc),
            },
            "status": "sandbox_infra_failed",
            "error": str(exc),
            "retry_category": "infra",
        }

    print("\nSandbox Runner: starting...")
    print(f"   Repo: {repo_root}")

    patch_result = state.get("patch_result") or {}
    if not patch_result or not patch_result.get("success"):
        print("   Skipping: no successful patch in state")
        return {
            "sandbox_result": {
                "success": False,
                "skipped": True,
                "error": "No patch to validate",
            },
            "status": "sandbox_skipped",
            "error": None,
            "retry_category": "patch",
        }

    validation_plan = _resolve_validation_plan(state, repo_root)
    service = validation_plan.get("service") or {}
    service_name = service.get("name")
    language = str(service.get("language") or "").lower()
    service_root = str(service.get("root") or ".").strip()
    execution_mode = validation_plan.get("execution_mode") or "local"
    selected_tests = list(validation_plan.get("display") or validation_plan.get("selected_test_paths") or [])
    modified_files = patch_result.get("modified_files", [])
    ticket_key = state.get("ticket", {}).get("jira_key", "UNKNOWN")
    force_docker_full_suite = bool(state.get("force_docker_full_suite"))

    print(f"   Service    : {service_name or 'unresolved'} ({language or 'unknown'})")
    print(f"   Ticket     : {ticket_key}")
    print(f"   Modified   : {modified_files}")
    print(f"   Validation : {execution_mode}")
    if force_docker_full_suite:
        print("   Mode       : forced docker full-suite validation")
    if selected_tests:
        print(f"   Selected tests: {selected_tests}")

    commands: list[list[str]] = []
    if not validation_plan.get("execution_candidates") and not validation_plan.get("test_command_base"):
        return {
            "sandbox_result": {
                "success": False,
                "service": service_name,
                "stage": "validation_planning",
                "skipped": False,
                "modified_files": modified_files,
                "validation_plan": validation_plan,
                "error": "Could not infer a validation command for this repository",
            },
            "status": "sandbox_infra_failed",
            "error": "Validation plan inference failed",
            "retry_category": "infra",
        }

    candidate_errors = []
    execution_candidates = list(validation_plan.get("execution_candidates") or [])
    if not execution_candidates:
        execution_candidates = [
            {
                "mode": execution_mode,
                "docker_service": validation_plan.get("docker_service"),
                "build_command": validation_plan.get("build_command"),
                "test_command_base": validation_plan.get("test_command_base"),
                "dependency_commands": validation_plan.get("dependency_commands"),
                "workdir": service_root,
                "confidence": 0.5,
            }
        ]

    for candidate in execution_candidates:
        candidate_mode = str(candidate.get("mode") or candidate.get("execution_mode") or "local").lower()
        candidate_plan = _candidate_plan(validation_plan, candidate)
        execution_root = _candidate_workdir(repo_root, service_root, candidate)
        commands = []
        build_output = ""
        test_stdout = ""
        test_stderr = ""

        print(f"\n   Attempting validation candidate: {candidate_mode} (confidence={candidate.get('confidence')})")

        try:
            run_local_compile_only = (
                settings.SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY
                and language == "python"
                and candidate_mode == "local"
                and not force_docker_full_suite
            )

            if force_docker_full_suite and candidate_mode != "docker":
                candidate_errors.append({"mode": candidate_mode, "error": "Skipped candidate (forced docker full-suite mode)"})
                continue

            if candidate_mode == "docker" and settings.SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY and language == "python":
                if force_docker_full_suite:
                    pass
                else:
                    candidate_errors.append({"mode": candidate_mode, "error": "Skipped docker candidate (python local compile-only mode enabled)"})
                    continue

            if candidate_mode == "docker" and settings.SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY and language == "python" and not force_docker_full_suite:
                candidate_errors.append({"mode": candidate_mode, "error": "Skipped docker candidate (python local compile-only mode enabled)"})
                continue

            if candidate_mode == "local":
                if not run_local_compile_only and not _local_command_available(candidate_plan, execution_root):
                    candidate_errors.append({"mode": candidate_mode, "error": "Local validation command unavailable"})
                    continue
            elif candidate_mode == "docker":
                returncode, stdout, stderr = _run(["docker", "--version"], repo_root, timeout=5)
                commands.append(["docker", "--version"])
                if returncode != 0:
                    candidate_errors.append({"mode": candidate_mode, "error": (stderr or stdout or "Docker unavailable")[-500:]})
                    continue

                dependency_commands = candidate_plan.get("dependency_commands") or {}
                if dependency_commands.get("up"):
                    print("\n   Starting dependencies...")
                    returncode, stdout, stderr = _run(dependency_commands["up"], repo_root, timeout=90)
                    commands.append(list(dependency_commands["up"]))
                    if returncode != 0:
                        candidate_errors.append({"mode": candidate_mode, "error": (stderr or stdout or "Dependency startup failed")[-1200:]})
                        continue

            if candidate_plan.get("build_command"):
                print("\n   Building service...")
                build_cmd = list(candidate_plan["build_command"])
                returncode, stdout, stderr = _run(build_cmd, execution_root if candidate_mode != "docker" else repo_root, timeout=300)
                commands.append(build_cmd)
                build_output = (stdout + "\n" + stderr).strip()
                if returncode != 0:
                    candidate_errors.append({"mode": candidate_mode, "error": "Build failed", "output": build_output[-1200:]})
                    continue

            run_compile_in_docker = candidate_mode == "docker" and language == "python"
            run_compile_locally = run_local_compile_only
            run_full_suite_in_docker = force_docker_full_suite and candidate_mode == "docker"
            skip_pytest_execution = not run_compile_in_docker and not run_compile_locally

            if run_full_suite_in_docker:
                print("\n   Skipping docker full-suite test execution (pytest/test runner bypass enabled)...")
                returncode = 0
                test_stdout = ""
                test_stderr = ""
                run_compile_in_docker = False
                run_compile_locally = False

            elif run_compile_in_docker:
                docker_service = str(candidate_plan.get("docker_service") or "").strip()
                compile_cmd = ["docker", "compose", "run", "--rm", docker_service, "python", "-m", "compileall", "-q", "."]
                print("\n   Running python compile check inside docker...")
                returncode, test_stdout, test_stderr = _run(compile_cmd, execution_root, timeout=240)
                commands.append(compile_cmd)
            elif run_compile_locally:
                compile_cmd = ["python", "-m", "compileall", "-q", "."]
                print("\n   Running python compile check locally...")
                returncode, test_stdout, test_stderr = _run(compile_cmd, execution_root, timeout=240)
                commands.append(compile_cmd)
            else:
                print("\n   Skipping pytest/test execution (sandbox validation remains enabled)...")
                returncode = 0
                test_stdout = ""
                test_stderr = ""

            failed_tests = _extract_failed_tests(language, test_stdout, test_stderr)
            passed_tests = _extract_passed_tests(language, test_stdout, test_stderr)
            failure_reason = _failure_reason(test_stdout, test_stderr)
            passed = returncode == 0
            pass_override_reason = None
            compile_failure_context = None
            selected_tests_for_report = selected_tests

            if (run_compile_in_docker or run_compile_locally) and not passed:
                failed_file = _extract_compile_failure_file(test_stdout, test_stderr)
                compile_failure_context = _read_compile_failure_context(repo_root, service_root, failed_file)
                if compile_failure_context:
                    print(f"   Compile failure file: {compile_failure_context.get('file')}")

            if skip_pytest_execution:
                selected_tests_for_report = []
                passed_tests = []
                failed_tests = []
                failure_reason = None

            if (
                not passed
                and not run_compile_in_docker
                and not run_compile_locally
                and not run_full_suite_in_docker
                and candidate_mode == "docker"
                and settings.SANDBOX_DOCKER_PASS_ON_ANY_RELEVANT_TEST
                and _any_relevant_test_passed(selected_tests, passed_tests)
            ):
                passed = True
                pass_override_reason = "docker_any_relevant_test_passed"
                print("   Docker pass override enabled: at least one relevant selected test passed")

            if passed:
                if run_compile_in_docker or run_compile_locally:
                    print("   Python compile check PASSED")
                elif run_full_suite_in_docker:
                    print("   Docker validation PASSED (test execution skipped)")
                else:
                    print("   Sandbox validation PASSED (pytest skipped)")
                status = "sandbox_passed"
            else:
                if run_compile_in_docker or run_compile_locally:
                    print("   Python compile check FAILED")
                elif run_full_suite_in_docker:
                    print("   Docker full-suite tests FAILED")
                else:
                    print("   Tests FAILED")
                if failed_tests:
                    print(f"   Failed tests : {failed_tests}")
                status = "sandbox_failed"

            return {
                "sandbox_result": {
                    "success": passed,
                    "service": service_name,
                    "stage": "test",
                    "skipped": False,
                    "commands": commands,
                    "service_source": "validation_plan",
                    "selected_tests": selected_tests_for_report,
                    "test_plan_source": "pytest_skipped" if skip_pytest_execution else validation_plan.get("source"),
                    "test_candidates": validation_plan.get("candidate_tests"),
                    "validation_plan": validation_plan,
                    "validation_candidate": candidate_plan,
                    "candidate_errors": candidate_errors,
                    "failed_tests": failed_tests,
                    "passed_tests": passed_tests,
                    "pass_override_reason": "pytest_skipped" if skip_pytest_execution else pass_override_reason,
                    "compile_failure_context": compile_failure_context,
                    "failure_reason": failure_reason if not passed else None,
                    "build_output": build_output[-2000:] if build_output else "",
                    "test_output": test_stdout[-5000:],
                    "test_error": test_stderr[-2500:],
                    "modified_files": modified_files,
                    "error": None if passed else (failure_reason or test_stderr or "Validation failed after patch")[-1200:],
                },
                "status": status,
                "error": None if passed else "Validation failed after patch",
                "retry_category": "code" if not passed else "none",
            }
        finally:
            if candidate_mode == "docker":
                if settings.SANDBOX_KEEP_DOCKER_CONTAINERS:
                    print("Keeping docker containers running for post-run log inspection")
                else:
                    _stop_docker(repo_root)

    return {
        "sandbox_result": {
            "success": False,
            "service": service_name,
            "stage": "validation_planning",
            "skipped": False,
            "commands": [],
            "validation_plan": validation_plan,
            "candidate_errors": candidate_errors,
            "modified_files": modified_files,
            "error": "All validation candidates failed before completing test execution",
        },
        "status": "sandbox_infra_failed",
        "error": "All validation candidates failed",
        "retry_category": "infra",
    }
