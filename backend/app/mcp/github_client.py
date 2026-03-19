import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import requests


def _run_cmd(cmd: list[str], cwd: Optional[str] = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(cmd)}")
    return result.stdout.strip()


def _run_cmd_with_code(cmd: list[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _on_rm_error(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _normalize_repo_id(repo_id: str) -> str:
    return repo_id.strip().replace("\\", "/").replace(".git", "")


def parse_repo_owner_name(repo_id: str) -> Tuple[str, str]:
    normalized = _normalize_repo_id(repo_id)
    parts = PurePosixPath(normalized).parts
    if len(parts) < 2:
        raise ValueError("repoId must be in OWNER/REPO format")
    return parts[-2], parts[-1]


def parse_owner_repo_from_url(repo_url: str) -> Optional[Tuple[str, str]]:
    if not repo_url:
        return None

    cleaned = repo_url.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", cleaned)
    if not match:
        return None
    return match.group(1), match.group(2)


def build_repo_url(repo_id: str) -> str:
    normalized = _normalize_repo_id(repo_id)
    return f"https://github.com/{normalized}.git"


def detect_local_github_repository(repo_root: str | Path) -> Dict[str, Any]:
    root = Path(repo_root).resolve()

    def run_git(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()

    remote_url = run_git(["config", "--get", "remote.origin.url"])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    commit_sha = run_git(["rev-parse", "HEAD"])
    owner_repo = parse_owner_repo_from_url(remote_url)
    return {
        "remote_url": remote_url or None,
        "owner": owner_repo[0] if owner_repo else None,
        "repo": owner_repo[1] if owner_repo else None,
        "branch": branch or None,
        "commit_sha": commit_sha or None,
    }


def _maybe_parse_json_text(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_paths_from_payload(payload: Any) -> List[str]:
    paths: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            path = node.get("path")
            if isinstance(path, str):
                paths.append(path)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    deduped: List[str] = []
    seen = set()
    for p in paths:
        normalized = p.replace("\\", "/")
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _extract_file_entries(payload: Any) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("type", "")).lower()
            path = node.get("path")
            if isinstance(path, str) and node_type in {"file", "dir"}:
                entries.append({"type": node_type, "path": path.replace("\\", "/")})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return entries


class GitHubMCPClient:
    def __init__(
        self,
        github_token: Optional[str] = None,
        mcp_server_command: Optional[str] = None,
        mcp_server_args: Optional[str] = None,
    ) -> None:
        if github_token is None or mcp_server_command is None or mcp_server_args is None:
            from app.config import settings

            github_token = settings.GITHUB_TOKEN if github_token is None else github_token
            mcp_server_command = settings.GITHUB_MCP_SERVER_COMMAND if mcp_server_command is None else mcp_server_command
            mcp_server_args = settings.GITHUB_MCP_SERVER_ARGS if mcp_server_args is None else mcp_server_args

        self.github_token = github_token
        self.mcp_server_command = str(mcp_server_command or "npx")
        self.mcp_server_args = shlex.split(mcp_server_args or "")

    def _run_checked(self, cmd: list[str], cwd: str) -> str:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {' '.join(cmd)}")
        return (result.stdout or "").strip()

    def _run_with_code(self, cmd: list[str], cwd: str) -> tuple[int, str, str]:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return result.returncode, (result.stdout or ""), (result.stderr or "")

    def _resolve_repo_coordinates(self, repo_root: Path) -> tuple[str, str]:
        from app.config import settings

        detected = detect_local_github_repository(repo_root)
        owner = str(detected.get("owner") or "").strip()
        repo = str(detected.get("repo") or "").strip()
        if owner and repo:
            return owner, repo

        configured_repo = str(settings.GITHUB_REPO or "").strip()
        if configured_repo:
            parsed = parse_owner_repo_from_url(configured_repo)
            if parsed:
                return parsed
            try:
                return parse_repo_owner_name(configured_repo)
            except Exception:
                pass

        raise RuntimeError("Could not resolve GitHub owner/repo from settings.GITHUB_REPO or local git remote")

    def create_fix_pr(
        self,
        *,
        ticket_key: str,
        file_path: str,
        fixed_content: str,
        ticket_summary: str,
        fix_reason: str,
        test_passed: bool,
        file_paths: Optional[List[str]] = None,
        repo_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.config import settings

        if not self.github_token:
            raise RuntimeError("GITHUB_TOKEN is not configured")

        repository_root = Path(repo_root or settings.TARGET_REPO_PATH).resolve()
        if not repository_root.exists():
            raise FileNotFoundError(f"Repository root does not exist: {repository_root}")

        primary_file = str(file_path or "").replace("\\", "/").strip()
        if not primary_file:
            raise ValueError("file_path is required for PR creation")

        primary_abs = (repository_root / primary_file).resolve()
        if not str(primary_abs).startswith(str(repository_root)):
            raise ValueError(f"Unsafe file path for PR creation: {primary_file}")
        primary_abs.parent.mkdir(parents=True, exist_ok=True)
        primary_abs.write_text(fixed_content, encoding="utf-8")

        owner, repo = self._resolve_repo_coordinates(repository_root)
        base_branch = str(settings.GITHUB_BASE_BRANCH or "main").strip() or "main"

        branch_key = re.sub(r"[^a-zA-Z0-9_-]", "-", str(ticket_key or "unknown")).strip("-").lower() or "unknown"
        branch_name = f"autofix/{branch_key}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        self._run_checked(["git", "checkout", "-B", branch_name], str(repository_root))

        normalized_files = []
        for item in (file_paths or [primary_file]):
            rel = str(item or "").replace("\\", "/").strip()
            if rel and rel not in normalized_files:
                normalized_files.append(rel)
        if primary_file not in normalized_files:
            normalized_files.insert(0, primary_file)

        add_candidates = [rel for rel in normalized_files if (repository_root / rel).exists()]
        if not add_candidates:
            raise RuntimeError("No modified files found in repository to commit for PR")

        self._run_checked(["git", "add", *add_candidates], str(repository_root))

        diff_code, _, _ = self._run_with_code(["git", "diff", "--cached", "--quiet"], str(repository_root))
        if diff_code == 0:
            raise RuntimeError("No staged changes to commit for PR")

        commit_message = f"fix({str(ticket_key or 'ticket').lower()}): {ticket_summary[:72]}"
        self._run_checked(["git", "commit", "-m", commit_message], str(repository_root))
        commit_sha = self._run_checked(["git", "rev-parse", "HEAD"], str(repository_root))

        self._run_checked(["git", "push", "-u", "origin", branch_name], str(repository_root))

        push_owner, push_repo = owner, repo
        configured_repo = str(settings.GITHUB_REPO or "").strip()
        configured_owner_repo: tuple[str, str] | None = None
        if configured_repo:
            parsed = parse_owner_repo_from_url(configured_repo)
            if parsed:
                configured_owner_repo = parsed
            else:
                try:
                    configured_owner_repo = parse_repo_owner_name(configured_repo)
                except Exception:
                    configured_owner_repo = None

        base_owner, base_repo = push_owner, push_repo
        head_ref = branch_name
        if configured_owner_repo:
            configured_owner, configured_name = configured_owner_repo
            # Safe override: only use configured base repo when repository name matches
            # the pushed repository (typical fork workflow keeps same repo name).
            if configured_name.lower() == push_repo.lower():
                base_owner, base_repo = configured_owner, configured_name
                head_ref = branch_name if configured_owner.lower() == push_owner.lower() else f"{push_owner}:{branch_name}"
            else:
                print(
                    "[WARN] GITHUB_REPO differs from push remote repository name; "
                    f"using push remote for PR base: {push_owner}/{push_repo}"
                )

        pr_title = f"[{ticket_key}] {ticket_summary}".strip()
        pr_body_lines = [
            f"Automated fix generated for **{ticket_key}**.",
            "",
            f"- Tests passed in sandbox: {'yes' if test_passed else 'no'}",
            f"- Primary file: `{primary_file}`",
            "- Files included:",
            *[f"  - `{rel}`" for rel in add_candidates],
            "",
            "### Fix rationale",
            str(fix_reason or "Automated fix generated by pipeline."),
        ]
        pr_body = "\n".join(pr_body_lines).strip()

        response = requests.post(
            f"https://api.github.com/repos/{base_owner}/{base_repo}/pulls",
            headers={
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": pr_title,
                "head": head_ref,
                "base": base_branch,
                "body": pr_body,
            },
            timeout=30,
        )

        if response.status_code >= 400:
            detail = response.text
            try:
                detail_json = response.json()
                detail = str(detail_json)
            except Exception:
                pass
            raise RuntimeError(
                f"GitHub PR API failed (status={response.status_code}) owner={base_owner} repo={base_repo} "
                f"head={head_ref} base={base_branch} detail={detail}"
            )

        payload = response.json()
        return {
            "pr_number": payload.get("number"),
            "pr_url": payload.get("html_url"),
            "branch": branch_name,
            "head": head_ref,
            "base_branch": base_branch,
            "owner": base_owner,
            "repo": base_repo,
            "push_owner": push_owner,
            "push_repo": push_repo,
            "commit_sha": commit_sha,
            "files": add_candidates,
        }

    async def _probe_repository_with_mcp_async(self, owner: str, repo: str, ref: Optional[str]) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            return {
                "status": "skipped",
                "message": "Python MCP client package not available",
                "error": str(exc),
            }

        if not self.github_token:
            return {
                "status": "skipped",
                "message": "GITHUB_TOKEN not configured; cannot authenticate GitHub MCP server",
            }

        env = os.environ.copy()
        env["GITHUB_TOKEN"] = self.github_token
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.github_token

        params = StdioServerParameters(
            command=self.mcp_server_command,
            args=self.mcp_server_args,
            env=env,
        )

        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tool_names = {tool.name for tool in listed.tools}

                    call_candidates = [
                        ("get_file_contents", {"owner": owner, "repo": repo, "path": "README.md", "ref": ref or "main"}),
                        ("get_file_contents", {"owner": owner, "repo": repo, "path": "README.md"}),
                        ("get_repository", {"owner": owner, "repo": repo}),
                        ("search_repositories", {"query": f"{owner}/{repo}", "perPage": 1}),
                    ]

                    for tool_name, arguments in call_candidates:
                        if tool_name not in tool_names:
                            continue
                        try:
                            response = await session.call_tool(tool_name, arguments)
                            response_preview = json.dumps(response.model_dump(), default=str)[:1000]
                            return {
                                "status": "ok",
                                "tool": tool_name,
                                "message": "GitHub MCP server verified repository access",
                                "responsePreview": response_preview,
                            }
                        except Exception:
                            continue

                    return {
                        "status": "warning",
                        "message": "MCP server connected but no compatible repository probe tool succeeded",
                        "availableTools": sorted(tool_names),
                    }
        except Exception as exc:
            return {
                "status": "warning",
                "message": "Failed to communicate with GitHub MCP server",
                "error": str(exc),
            }

    def probe_repository_with_mcp(self, owner: str, repo: str, ref: Optional[str]) -> Dict[str, Any]:
        import asyncio

        return asyncio.run(self._probe_repository_with_mcp_async(owner, repo, ref))

    async def _discover_history_related_paths_async(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        seed_paths: List[str],
        max_paths: int = 8,
    ) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            return {
                "status": "error",
                "message": "Python MCP client package not available",
                "error": str(exc),
                "paths": [],
            }

        if not self.github_token:
            return {
                "status": "error",
                "message": "GITHUB_TOKEN not configured",
                "paths": [],
            }

        env = os.environ.copy()
        env["GITHUB_TOKEN"] = self.github_token
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.github_token

        params = StdioServerParameters(
            command=self.mcp_server_command,
            args=self.mcp_server_args,
            env=env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_names = {tool.name for tool in listed.tools}

                history_paths: list[str] = []
                seen = set()

                def add_path(path_value: str) -> None:
                    normalized = str(path_value or "").strip().replace("\\", "/")
                    if not normalized or normalized in seen:
                        return
                    seen.add(normalized)
                    history_paths.append(normalized)

                commit_tools = [name for name in ["list_commits", "search_commits", "get_commit"] if name in tool_names]
                for tool_name in commit_tools:
                    if tool_name == "list_commits":
                        arg_sets = [
                            {"owner": owner, "repo": repo, "sha": ref or "HEAD", "perPage": 10},
                            {"owner": owner, "repo": repo, "per_page": 10},
                            {"owner": owner, "repo": repo},
                        ]
                    elif tool_name == "search_commits":
                        queries = [f"{owner}/{repo} {' '.join(Path(path).name for path in seed_paths[:2])}".strip()]
                        arg_sets = [{"query": query, "perPage": 10} for query in queries]
                    else:
                        arg_sets = []

                    for args in arg_sets:
                        try:
                            response = await session.call_tool(tool_name, args)
                        except Exception:
                            continue
                        texts = [
                            getattr(item, "text", "")
                            for item in getattr(response, "content", [])
                            if getattr(item, "type", "") == "text"
                        ]
                        for text in texts:
                            parsed = _maybe_parse_json_text(text)
                            if parsed is None:
                                continue
                            for path in _extract_paths_from_payload(parsed):
                                add_path(path)
                        if history_paths:
                            break
                    if history_paths:
                        break

                return {
                    "status": "ok" if history_paths else "no_results",
                    "paths": history_paths[:max_paths],
                    "tools": sorted(tool_names),
                }

    async def _discover_candidate_files_async(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        terms: List[str],
        likely_files: List[str],
        max_files: int = 8,
    ) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            return {
                "status": "error",
                "message": "Python MCP client package not available",
                "error": str(exc),
                "paths": [],
            }

        if not self.github_token:
            return {
                "status": "error",
                "message": "GITHUB_TOKEN not configured",
                "paths": [],
            }

        env = os.environ.copy()
        env["GITHUB_TOKEN"] = self.github_token
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.github_token

        params = StdioServerParameters(
            command=self.mcp_server_command,
            args=self.mcp_server_args,
            env=env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_names = {tool.name for tool in listed.tools}

                candidate_paths: List[str] = []
                seen_paths = set()

                def add_path(path_value: str) -> None:
                    normalized = str(path_value or "").strip().replace("\\", "/")
                    if not normalized or normalized in seen_paths:
                        return
                    candidate_paths.append(normalized)
                    seen_paths.add(normalized)

                for item in likely_files:
                    add_path(item)

                if "search_code" in tool_names:
                    search_terms = [t.strip() for t in terms if t and t.strip()]
                    search_terms.extend(likely_files)
                    for term in search_terms[:8]:
                        queries = [
                            {"query": f"{term} repo:{owner}/{repo}", "perPage": 8},
                            {"q": f"{term} repo:{owner}/{repo}", "per_page": 8},
                            {"query": term, "owner": owner, "repo": repo, "perPage": 8},
                        ]
                        for args in queries:
                            try:
                                response = await session.call_tool("search_code", args)
                                texts = [
                                    getattr(item, "text", "")
                                    for item in getattr(response, "content", [])
                                    if getattr(item, "type", "") == "text"
                                ]
                                for text in texts:
                                    parsed = _maybe_parse_json_text(text)
                                    if parsed is None:
                                        continue
                                    for path in _extract_paths_from_payload(parsed):
                                        add_path(path)
                                break
                            except Exception:
                                continue

                if not candidate_paths and "get_file_contents" in tool_names:
                    visited_dirs = set()
                    queue = ["", "python-service", "node-service", "app", "src"]

                    async def fetch_path_payload(path_value: str) -> Any:
                        args_candidates = [
                            {"owner": owner, "repo": repo, "path": path_value, "ref": ref or "main"},
                            {"owner": owner, "repo": repo, "path": path_value},
                        ]
                        for call_args in args_candidates:
                            try:
                                response = await session.call_tool("get_file_contents", call_args)
                                texts = [
                                    getattr(item, "text", "")
                                    for item in getattr(response, "content", [])
                                    if getattr(item, "type", "") == "text"
                                ]
                                for text in texts:
                                    parsed = _maybe_parse_json_text(text)
                                    if parsed is not None:
                                        return parsed
                            except Exception:
                                continue
                        return None

                    discovered_files: List[str] = []
                    while queue and len(discovered_files) < 400:
                        current = queue.pop(0)
                        current_key = current.strip("/")
                        if current_key in visited_dirs:
                            continue
                        visited_dirs.add(current_key)
                        payload = await fetch_path_payload(current)
                        if payload is None:
                            continue
                        for entry in _extract_file_entries(payload):
                            entry_type = entry["type"]
                            entry_path = entry["path"]
                            if entry_type == "file":
                                discovered_files.append(entry_path)
                            elif entry_type == "dir" and entry_path not in visited_dirs and len(queue) < 200:
                                queue.append(entry_path)

                    likely_basenames = {item.split("/")[-1].lower() for item in likely_files if item}
                    likely_stems = {
                        name.rsplit(".", 1)[0] if "." in name else name
                        for name in likely_basenames
                    }
                    keyword_terms = [str(t).lower() for t in terms if t]
                    weak_terms = {
                        "python-service",
                        "node-service",
                        "logic_error",
                        "runtime_error",
                        "security_vulnerability",
                        "config_error",
                        "null_pointer",
                        "type_error",
                        "syntax_error",
                        "unknown",
                    }
                    keyword_terms = [term for term in keyword_terms if term not in weak_terms and len(term) >= 4]

                    scored_candidates: List[Tuple[int, str]] = []
                    for path in discovered_files:
                        lowered = path.lower()
                        basename = lowered.split("/")[-1]
                        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
                        score = 0
                        if basename in likely_basenames:
                            score += 120
                        if stem in likely_stems:
                            score += 90
                        if any(ls and ls in stem for ls in likely_stems):
                            score += 40
                        score += sum(8 for term in keyword_terms if term in basename)
                        score += sum(3 for term in keyword_terms if term in lowered)
                        if lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".cs")):
                            score += 20
                        if lowered.endswith((".md", ".env", ".env.example", "dockerfile")):
                            score -= 20
                        if score > 0:
                            scored_candidates.append((score, path))

                    scored_candidates.sort(key=lambda item: item[0], reverse=True)
                    for _, path in scored_candidates[: max_files * 2]:
                        add_path(path)

                return {
                    "status": "ok" if candidate_paths else "no_results",
                    "paths": candidate_paths[:max_files],
                    "tools": sorted(tool_names),
                    "ref": ref or "main",
                }

    def discover_candidate_files(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        terms: List[str],
        likely_files: List[str],
        max_files: int = 8,
    ) -> Dict[str, Any]:
        import asyncio

        return asyncio.run(
            self._discover_candidate_files_async(
                owner=owner,
                repo=repo,
                ref=ref,
                terms=terms,
                likely_files=likely_files,
                max_files=max_files,
            )
        )

    def discover_history_related_paths(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        seed_paths: List[str],
        max_paths: int = 8,
    ) -> Dict[str, Any]:
        import asyncio

        return asyncio.run(
            self._discover_history_related_paths_async(
                owner=owner,
                repo=repo,
                ref=ref,
                seed_paths=seed_paths,
                max_paths=max_paths,
            )
        )

    async def _retrieve_code_context_async(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        terms: List[str],
        likely_files: List[str],
        max_files: int = 5,
    ) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            return {
                "status": "error",
                "message": "Python MCP client package not available",
                "error": str(exc),
                "files": [],
            }

        if not self.github_token:
            return {
                "status": "error",
                "message": "GITHUB_TOKEN not configured",
                "files": [],
            }

        env = os.environ.copy()
        env["GITHUB_TOKEN"] = self.github_token
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self.github_token

        params = StdioServerParameters(
            command=self.mcp_server_command,
            args=self.mcp_server_args,
            env=env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_names = {tool.name for tool in listed.tools}

                candidate_paths: List[str] = []
                for item in likely_files:
                    value = (item or "").strip().replace("\\", "/")
                    if value and value not in candidate_paths:
                        candidate_paths.append(value)

                if "search_code" in tool_names:
                    search_terms = [t.strip() for t in terms if t and t.strip()]
                    search_terms.extend(likely_files)
                    seen_paths = set(candidate_paths)

                    for term in search_terms[:8]:
                        queries = [
                            {"query": f"{term} repo:{owner}/{repo}", "perPage": 8},
                            {"q": f"{term} repo:{owner}/{repo}", "per_page": 8},
                            {"query": term, "owner": owner, "repo": repo, "perPage": 8},
                        ]

                        for args in queries:
                            try:
                                response = await session.call_tool("search_code", args)
                                texts = [
                                    getattr(item, "text", "")
                                    for item in getattr(response, "content", [])
                                    if getattr(item, "type", "") == "text"
                                ]
                                for text in texts:
                                    parsed = _maybe_parse_json_text(text)
                                    if parsed is None:
                                        continue
                                    for path in _extract_paths_from_payload(parsed):
                                        if path not in seen_paths:
                                            candidate_paths.append(path)
                                            seen_paths.add(path)
                                break
                            except Exception:
                                continue

                files: List[Dict[str, Any]] = []

                async def fetch_path_payload(path_value: str) -> Any:
                    args_candidates = [
                        {"owner": owner, "repo": repo, "path": path_value, "ref": ref or "main"},
                        {"owner": owner, "repo": repo, "path": path_value},
                    ]
                    for call_args in args_candidates:
                        try:
                            response = await session.call_tool("get_file_contents", call_args)
                            texts = [
                                getattr(item, "text", "")
                                for item in getattr(response, "content", [])
                                if getattr(item, "type", "") == "text"
                            ]
                            for text in texts:
                                parsed = _maybe_parse_json_text(text)
                                if parsed is not None:
                                    return parsed
                        except Exception:
                            continue
                    return None

                for path in candidate_paths:
                    if len(files) >= max_files:
                        break
                    fetch_args_candidates = [
                        {"owner": owner, "repo": repo, "path": path, "ref": ref or "main"},
                        {"owner": owner, "repo": repo, "path": path},
                    ]

                    for args in fetch_args_candidates:
                        try:
                            response = await session.call_tool("get_file_contents", args)
                            texts = [
                                getattr(item, "text", "")
                                for item in getattr(response, "content", [])
                                if getattr(item, "type", "") == "text"
                            ]
                            if not texts:
                                continue

                            parsed = _maybe_parse_json_text(texts[0])
                            if isinstance(parsed, dict):
                                file_path = parsed.get("path") or path
                                content = parsed.get("content") or ""
                            else:
                                file_path = path
                                content = texts[0]

                            files.append(
                                {
                                    "path": str(file_path).replace("\\", "/"),
                                    "content": content,
                                }
                            )
                            break
                        except Exception:
                            continue

                if not files:
                    discovered_files: List[str] = []
                    visited_dirs = set()
                    queue = ["", "python-service", "node-service", "app", "src"]

                    while queue and len(discovered_files) < 400:
                        current = queue.pop(0)
                        current_key = current.strip("/")
                        if current_key in visited_dirs:
                            continue
                        visited_dirs.add(current_key)

                        payload = await fetch_path_payload(current)
                        if payload is None:
                            continue

                        entries = _extract_file_entries(payload)
                        for entry in entries:
                            entry_type = entry["type"]
                            entry_path = entry["path"]
                            if entry_type == "file" and entry_path not in discovered_files:
                                discovered_files.append(entry_path)
                            elif entry_type == "dir" and entry_path not in visited_dirs and len(queue) < 200:
                                queue.append(entry_path)

                    likely_basenames = {item.split("/")[-1].lower() for item in likely_files if item}
                    likely_stems = {
                        name.rsplit(".", 1)[0] if "." in name else name
                        for name in likely_basenames
                    }
                    keyword_terms = [str(t).lower() for t in terms if t]
                    weak_terms = {
                        "python-service",
                        "node-service",
                        "logic_error",
                        "runtime_error",
                        "security_vulnerability",
                        "config_error",
                        "null_pointer",
                        "type_error",
                        "syntax_error",
                        "unknown",
                    }
                    keyword_terms = [term for term in keyword_terms if term not in weak_terms and len(term) >= 4]

                    scored_candidates: List[Tuple[int, str]] = []
                    for path in discovered_files:
                        lowered = path.lower()
                        basename = lowered.split("/")[-1]
                        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
                        score = 0

                        if basename in likely_basenames:
                            score += 120
                        if stem in likely_stems:
                            score += 90
                        if any(ls and ls in stem for ls in likely_stems):
                            score += 40

                        score += sum(8 for term in keyword_terms if term in basename)
                        score += sum(3 for term in keyword_terms if term in lowered)

                        if lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".cs")):
                            score += 20
                        if lowered.endswith((".md", ".env", ".env.example", "dockerfile")):
                            score -= 20

                        if score > 0:
                            scored_candidates.append((score, path))

                    scored_candidates.sort(key=lambda item: item[0], reverse=True)
                    candidate_matches = [path for _, path in scored_candidates]

                    for path in candidate_matches[: max_files * 4]:
                        if len(files) >= max_files:
                            break
                        payload = await fetch_path_payload(path)
                        if isinstance(payload, dict):
                            content = payload.get("content") or ""
                            file_path = payload.get("path") or path
                            if content:
                                files.append(
                                    {
                                        "path": str(file_path).replace("\\", "/"),
                                        "content": content,
                                    }
                                )

                return {
                    "status": "ok" if files else "no_results",
                    "files": files,
                    "tools": sorted(tool_names),
                }

    def retrieve_code_context(
        self,
        owner: str,
        repo: str,
        ref: Optional[str],
        terms: List[str],
        likely_files: List[str],
        max_files: int = 5,
    ) -> Dict[str, Any]:
        import asyncio

        return asyncio.run(
            self._retrieve_code_context_async(
                owner=owner,
                repo=repo,
                ref=ref,
                terms=terms,
                likely_files=likely_files,
                max_files=max_files,
            )
        )

    def clone_or_update_repository(
        self,
        repo_url: str,
        repo_id: str,
        ref: Optional[str],
        base_dir: str,
    ) -> Dict[str, Any]:
        def _try_checkout(local_repo_path: str, target_ref: str) -> tuple[bool, str]:
            code, out, err = _run_cmd_with_code(["git", "-C", local_repo_path, "checkout", target_ref])
            return code == 0, (err or out)

        def _resolve_origin_default_branch(local_repo_path: str) -> Optional[str]:
            code, out, _ = _run_cmd_with_code(
                ["git", "-C", local_repo_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]
            )
            if code != 0 or not out:
                return None
            normalized = out.strip().replace("\\", "/")
            if normalized.startswith("origin/"):
                return normalized.split("/", 1)[1]
            return normalized

        local_path = os.path.join(base_dir, repo_id.replace("/", os.sep))
        git_dir = os.path.join(local_path, ".git")

        if not os.path.exists(local_path):
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            _run_cmd(["git", "clone", repo_url, local_path])
            operation = "cloned"
        elif not os.path.exists(git_dir):
            shutil.rmtree(local_path, onerror=_on_rm_error)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            _run_cmd(["git", "clone", repo_url, local_path])
            operation = "recloned"
        else:
            _run_cmd(["git", "-C", local_path, "fetch", "--all", "--prune"])
            operation = "updated"

        requested_ref = str(ref or "").strip()
        primary_ref = requested_ref or "main"
        checkout_attempts: list[tuple[str, str]] = []

        success, message = _try_checkout(local_path, primary_ref)
        checkout_attempts.append((primary_ref, message))
        checked_out_ref = primary_ref if success else None

        if not success and requested_ref:
            success, message = _try_checkout(local_path, f"origin/{requested_ref}")
            checkout_attempts.append((f"origin/{requested_ref}", message))
            if success:
                _run_cmd(["git", "-C", local_path, "checkout", "-B", requested_ref, f"origin/{requested_ref}"])
                checked_out_ref = requested_ref

        if checked_out_ref is None:
            default_branch = _resolve_origin_default_branch(local_path)
            fallback_refs: list[str] = []
            if default_branch:
                fallback_refs.append(default_branch)
            fallback_refs.extend(["main", "master"])

            seen = set()
            deduped_fallbacks = []
            for candidate in fallback_refs:
                normalized = str(candidate).strip()
                if normalized and normalized not in seen:
                    deduped_fallbacks.append(normalized)
                    seen.add(normalized)

            for candidate in deduped_fallbacks:
                success, message = _try_checkout(local_path, candidate)
                checkout_attempts.append((candidate, message))
                if success:
                    checked_out_ref = candidate
                    break

        if checked_out_ref is None:
            _, branches_out, _ = _run_cmd_with_code(["git", "-C", local_path, "branch", "-a"])
            attempts_preview = "; ".join([f"{name}: {msg}" for name, msg in checkout_attempts if msg])
            raise RuntimeError(
                "Unable to checkout requested git ref. "
                f"Requested='{requested_ref or '(empty)'}'. "
                f"Attempts=[{attempts_preview}]. "
                f"Available branches:\n{branches_out}"
            )

        commit_sha = _run_cmd(["git", "-C", local_path, "rev-parse", "HEAD"])

        return {
            "localPath": local_path,
            "commitSha": commit_sha,
            "operation": operation,
            "checkedOutRef": checked_out_ref,
        }
