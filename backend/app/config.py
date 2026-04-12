import os
from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Ensure values in `.env` take precedence over any previously-exported environment variables.
# This avoids "stale credentials" when rotating Jira credentials in the `.env` file.
_DOTENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_DOTENV_PATH, override=True)

def resolve_path_to_absolute(raw_path: Optional[str], base_for_relative: Optional[str] = None) -> str:
    """
    Resolve a path string to an absolute path.

    Args:
        raw_path: The path to resolve (can be relative, absolute, or with ~)
        base_for_relative: If raw_path is relative, resolve it relative to this base.
                          If None, use PROJECT_ROOT.

    Returns:
        Absolute path as a string.

    Handles:
        - Relative paths (./repos, repos/, etc.)
        - Home directory expansion (~)
        - Absolute paths (already absolute, just normalized)
    """
    if not raw_path:
        raw_path = "./repos"

    path_str = str(raw_path).strip()
    if not path_str:
        path_str = "./repos"

    # Remove surrounding quotes if present (from .env files)
    path_str = path_str.strip('"').strip("'")

    # Normalize path separators
    path_str = path_str.replace("\\", "/")

    # Expand home directory (~)
    expanded = os.path.expanduser(path_str)

    # If already absolute, just return it
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)

    # If relative, resolve relative to the specified base
    if base_for_relative is None:
        base_for_relative = str(PROJECT_ROOT)

    resolved = os.path.join(base_for_relative, expanded)
    return os.path.abspath(resolved)

class Settings(BaseSettings):
    OPENAI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    CEREBRAS_API_KEY: Optional[str] = None
    CEREBRAS_MODEL: str = "qwen-3-235b-a22b-instruct-2507"
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "qwen/qwen3-32b"
    OPENROUTER_APP_NAME: str = "test"
    OPENROUTER_HTTP_REFERER: Optional[str] = None
    JIRA_URL: str
    JIRA_EMAIL: str
    JIRA_API_TOKEN: str
    JIRA_PROJECT_KEY: str = "ST"
    JIRA_EXCLUDED_TICKET_KEYS: str = "ST-10,ST-9,ST-8"
    SUPABASE_URL: str
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    REPOS_BASE_DIR: Optional[str] = None
    TARGET_REPO_ID: Optional[str] = None
    TARGET_REPO_COMMIT_SHA: Optional[str] = None
    TARGET_REPO_PATH: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: Optional[str] = None
    GITHUB_BASE_BRANCH: Optional[str] = None
    GITHUB_MCP_SERVER_COMMAND: str = "npx"
    GITHUB_MCP_SERVER_ARGS: str = "-y @modelcontextprotocol/server-github"
    SANDBOX_KEEP_DOCKER_CONTAINERS: bool = True
    SANDBOX_DOCKER_PASS_ON_ANY_RELEVANT_TEST: bool = True
    PATCH_DISABLE_VALIDATIONS: bool = True
    SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY: bool = False
    LLM_MAX_GENERATION_RETRIES: int = 6
    SANDBOX_RUN_DOCKER_FULL_SUITE_AFTER_BATCH: bool = True
    SANDBOX_AUTO_REPAIR_AFTER_POST_BATCH_FAILURE: bool = True
    SANDBOX_AUTO_REPAIR_MAX_ATTEMPTS: int = 1
    AUTO_RUN_DOCKER_AFTER_CLONE: bool = True
    DOCKER_AUTOHEAL_MAX_CYCLES: int = 6
    DOCKER_AUTOHEAL_FIX_ATTEMPTS: int = 6
    FRONTEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        extra="ignore",
    )

    @model_validator(mode="after")
    def populate_supabase_key(self) -> "Settings":
        if not self.SUPABASE_KEY and self.SUPABASE_SERVICE_ROLE_KEY:
            self.SUPABASE_KEY = self.SUPABASE_SERVICE_ROLE_KEY
        return self

    @model_validator(mode="after")
    def resolve_paths_to_absolute(self) -> "Settings":
        """
        Ensure TARGET_REPO_PATH is an absolute path if set.
        REPOS_BASE_DIR is now optional and NOT used from config;
        it's only provided by the frontend form.
        """
        if self.TARGET_REPO_PATH:
            resolved = resolve_path_to_absolute(self.TARGET_REPO_PATH)
            if resolved:
                self.TARGET_REPO_PATH = resolved

        return self

    @property
    def jira_excluded_ticket_keys(self) -> list[str]:
        raw_value = str(self.JIRA_EXCLUDED_TICKET_KEYS or "")
        return [item.strip().upper() for item in raw_value.split(",") if item.strip()]

    @property
    def frontend_cors_origins(self) -> list[str]:
        raw_value = str(self.FRONTEND_CORS_ORIGINS or "")
        return [item.strip() for item in raw_value.split(",") if item.strip()]

settings = Settings()


def get_settings(*, reload: bool = False) -> Settings:
    """
    Return a Settings instance. When `reload=True`, re-load `.env` (overriding
    any existing process env vars) and re-instantiate Settings.
    """
    global settings
    if reload:
        load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
        settings = Settings()
    return settings

# Log resolved paths at startup for visibility
_resolved_target_repo = getattr(settings, "TARGET_REPO_PATH", None)
print(f"[Config] TARGET_REPO_PATH resolved to: {_resolved_target_repo}")
print(f"[Config] REPOS_BASE_DIR is not used from config - it's provided by the frontend form")

if __name__ == "__main__":
    print("Testing config...")
    print(f"Jira URL: {settings.JIRA_URL}")
    print("Config works!")
