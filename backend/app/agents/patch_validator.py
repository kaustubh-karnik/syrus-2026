from pathlib import Path

from app.agents.state import AgentState


VALID_EDIT_OPERATIONS = {"replace", "insert_after", "insert_before", "create_file"}


def _normalize_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/")


def _safe_rel_path(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("../"):
        return False
    return ".." not in Path(rel_path).parts


def patch_validator_node(state: AgentState) -> AgentState:
    repo_path = str(state.get("repo_path") or "").strip()
    fix = state.get("fix") or {}

    if not repo_path:
        return {
            "patch_validation_result": {
                "success": False,
                "status": "invalid",
                "errors": ["Target repository path is missing in state"],
            },
            "status": "invalid_patch",
            "failure_type": "invalid_patch_contract",
            "retry_category": "patch",
            "error": "Target repository path is missing in state",
        }

    repo_root = Path(repo_path).resolve()
    if not repo_root.exists() or not repo_root.is_dir():
        return {
            "patch_validation_result": {
                "success": False,
                "status": "invalid",
                "errors": [f"Target repository path does not exist: {repo_root}"],
            },
            "status": "invalid_patch",
            "failure_type": "invalid_patch_contract",
            "retry_category": "patch",
            "error": f"Target repository path does not exist: {repo_root}",
        }

    edits = fix.get("edits") or []
    if not isinstance(edits, list) or not edits:
        return {
            "patch_validation_result": {
                "success": False,
                "status": "invalid",
                "errors": ["Fix payload does not include any edits"],
            },
            "status": "invalid_patch",
            "failure_type": "invalid_patch_contract",
            "retry_category": "patch",
            "error": "Fix payload does not include any edits",
        }

    errors: list[str] = []
    validated_files: list[str] = []

    for index, raw_edit in enumerate(edits, start=1):
        if not isinstance(raw_edit, dict):
            errors.append(f"Edit #{index} is not a JSON object")
            continue

        operation = str(raw_edit.get("operation") or "").strip().lower()
        rel_file = _normalize_path(raw_edit.get("file") or "")
        target = str(raw_edit.get("target") or "")
        replacement = str(raw_edit.get("replacement") or "")

        if operation not in VALID_EDIT_OPERATIONS:
            errors.append(f"Edit #{index} uses unsupported operation: {operation or 'missing'}")

        if not _safe_rel_path(rel_file):
            errors.append(f"Edit #{index} has invalid file path: {rel_file or 'missing'}")
            continue

        abs_file = (repo_root / rel_file).resolve()
        if not str(abs_file).startswith(str(repo_root)):
            errors.append(f"Edit #{index} resolves outside repository: {rel_file}")
            continue

        if operation != "create_file":
            if not abs_file.exists() or not abs_file.is_file():
                errors.append(f"Edit #{index} target file does not exist: {rel_file}")
            if not target.strip():
                errors.append(f"Edit #{index} missing target for operation '{operation}'")

        if operation == "create_file" and abs_file.exists():
            errors.append(f"Edit #{index} create_file points to existing file: {rel_file}")

        if not replacement.strip():
            errors.append(f"Edit #{index} has empty replacement content")

        if rel_file and rel_file not in validated_files:
            validated_files.append(rel_file)

    if errors:
        return {
            "patch_validation_result": {
                "success": False,
                "status": "invalid",
                "errors": errors,
                "validated_files": validated_files,
            },
            "status": "invalid_patch",
            "failure_type": "invalid_patch_contract",
            "retry_category": "patch",
            "error": errors[0],
        }

    return {
        "patch_validation_result": {
            "success": True,
            "status": "valid",
            "errors": [],
            "validated_files": validated_files,
            "validated_edit_count": len(edits),
        },
        "status": "patch_validated",
        "failure_type": None,
        "error": None,
    }
