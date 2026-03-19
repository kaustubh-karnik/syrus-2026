import subprocess
from pathlib import Path
from typing import Any, Dict

from app.agents.pipeline import run_pipeline_with_retries
from app.config import settings


COMPOSE_FILENAMES = [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
]


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str, str]:
    print(f"[DockerAutoFix] Running command: {' '.join(cmd)} (cwd={cwd})")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        print(f"[DockerAutoFix] Command exit={result.returncode}")
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", f"timed out after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def _find_compose_file(repo_root: Path) -> Path | None:
    for name in COMPOSE_FILENAMES:
        candidate = repo_root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _docker_up(repo_root: Path, compose_file: Path) -> tuple[bool, dict]:
    cmd = ["docker", "compose", "-f", compose_file.name, "up", "-d", "--build"]
    code, out, err = _run(cmd, repo_root, timeout=420)
    payload = {
        "command": cmd,
        "stdout": out[-5000:],
        "stderr": err[-5000:],
        "exit_code": code,
    }
    return code == 0, payload


def _docker_ps(repo_root: Path, compose_file: Path) -> dict:
    cmd = ["docker", "compose", "-f", compose_file.name, "ps"]
    code, out, err = _run(cmd, repo_root, timeout=60)
    return {
        "command": cmd,
        "stdout": out[-5000:],
        "stderr": err[-5000:],
        "exit_code": code,
    }


def _build_autoheal_ticket(repo_id: str, cycle: int, docker_error: dict) -> dict:
    combined_error = f"{docker_error.get('stdout', '')}\n{docker_error.get('stderr', '')}".strip()
    return {
        "jira_key": f"AUTO-DOCKER-{repo_id}-{cycle}",
        "summary": f"Auto-heal docker startup failure for {repo_id} (cycle {cycle})",
        "description": (
            "Repository docker startup failed after clone. Fix Docker/dependency/config issues so the container stack starts cleanly.\n\n"
            f"Docker command: {' '.join(docker_error.get('command') or [])}\n"
            f"Exit code: {docker_error.get('exit_code')}\n"
            f"Error log tail:\n{combined_error[-6000:]}"
        ),
        "priority": "High",
        "status": "Open",
    }


def run_docker_autofix_after_clone(local_repo_path: str, repo_id: str) -> Dict[str, Any]:
    repo_root = Path(local_repo_path).resolve()
    print(f"\n[DockerAutoFix] Starting docker auto-heal for repoId={repo_id} path={repo_root}")
    if not repo_root.exists():
        return {
            "status": "error",
            "message": f"Local repository path not found: {repo_root}",
        }

    compose_file = _find_compose_file(repo_root)
    if not compose_file:
        print("[DockerAutoFix] No compose file found; skipping docker auto-heal")
        return {
            "status": "skipped",
            "message": "No docker compose file found in cloned repository",
            "localRepoPath": str(repo_root),
        }

    cycles = max(1, int(settings.DOCKER_AUTOHEAL_MAX_CYCLES or 1))
    fix_attempts = max(1, int(settings.DOCKER_AUTOHEAL_FIX_ATTEMPTS or 1))
    print(f"[DockerAutoFix] composeFile={compose_file.name} maxCycles={cycles} fixAttemptsPerCycle={fix_attempts}")
    cycle_reports: list[dict] = []

    for cycle in range(1, cycles + 1):
        print(f"\n[DockerAutoFix] Cycle {cycle}/{cycles}: docker compose up")
        up_ok, docker_run = _docker_up(repo_root, compose_file)
        ps_info = _docker_ps(repo_root, compose_file)

        cycle_report = {
            "cycle": cycle,
            "docker_up": docker_run,
            "docker_ps": ps_info,
            "fixed": False,
            "pipeline": None,
        }

        if up_ok:
            print("[DockerAutoFix] Docker stack is healthy after compose up")
            cycle_report["fixed"] = True
            cycle_reports.append(cycle_report)
            return {
                "status": "ok",
                "message": "Docker stack started successfully",
                "localRepoPath": str(repo_root),
                "composeFile": compose_file.name,
                "cyclesUsed": cycle,
                "reports": cycle_reports,
            }

        ticket = _build_autoheal_ticket(repo_id, cycle, docker_run)
        print("[DockerAutoFix] Docker up failed. Triggering pipeline auto-fix...")
        pipeline_state = run_pipeline_with_retries(
            ticket,
            max_attempts=fix_attempts,
            target_repo_path=str(repo_root),
            initial_retry_feedback=(
                "Fix docker/dependency errors until docker compose up -d --build succeeds. "
                f"Error details:\n{(docker_run.get('stderr') or docker_run.get('stdout') or '')[-5000:]}"
            ),
        )
        cycle_report["pipeline"] = {
            "status": pipeline_state.get("status"),
            "error": pipeline_state.get("error"),
            "attempt_count": pipeline_state.get("attempt_count"),
            "patch_result": pipeline_state.get("patch_result"),
            "sandbox_result": pipeline_state.get("sandbox_result"),
        }
        print(
            "[DockerAutoFix] Pipeline cycle result: "
            f"status={cycle_report['pipeline'].get('status')} "
            f"attempts={cycle_report['pipeline'].get('attempt_count')}"
        )
        cycle_reports.append(cycle_report)

    print("[DockerAutoFix] Exhausted all cycles; docker stack still failing")
    return {
        "status": "error",
        "message": "Docker stack still failing after auto-heal cycles",
        "localRepoPath": str(repo_root),
        "composeFile": compose_file.name,
        "cyclesUsed": cycles,
        "reports": cycle_reports,
    }
