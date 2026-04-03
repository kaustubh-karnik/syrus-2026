from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    GROQ_API_KEY: str
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "qwen/qwen3-32b"
    OPENROUTER_APP_NAME: str = "Syrus2026_LOVE_AT_FIRST_BYTE"
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
    TARGET_REPO_PATH: str = r"C:\Users\Kaustubh\kk\Coding\syrus-2026-project"
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: Optional[str] = None
    GITHUB_BASE_BRANCH: Optional[str] = None
    GITHUB_MCP_SERVER_COMMAND: str = "npx"
    GITHUB_MCP_SERVER_ARGS: str = "-y @modelcontextprotocol/server-github"
    SANDBOX_KEEP_DOCKER_CONTAINERS: bool = True
    SANDBOX_DOCKER_PASS_ON_ANY_RELEVANT_TEST: bool = True
    PATCH_DISABLE_VALIDATIONS: bool = True
    SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY: bool = True
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

    @property
    def jira_excluded_ticket_keys(self) -> list[str]:
        raw_value = str(self.JIRA_EXCLUDED_TICKET_KEYS or "")
        return [item.strip().upper() for item in raw_value.split(",") if item.strip()]

    @property
    def frontend_cors_origins(self) -> list[str]:
        raw_value = str(self.FRONTEND_CORS_ORIGINS or "")
        return [item.strip() for item in raw_value.split(",") if item.strip()]

settings = Settings()

if __name__ == "__main__":
    print("Testing config...")
    print(f"Jira URL: {settings.JIRA_URL}")
    print("Config works!")
