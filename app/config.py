"""Application settings, loaded from the environment / .env via pydantic-settings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret-change-me-to-a-long-random-value-32b"
    database_url: str = "sqlite+aiosqlite:///./agentflow.db"

    # LLM
    anthropic_api_key: str = ""
    chat_model: str = "claude-sonnet-5"
    use_fake_agent: bool = False
    max_tokens: int = 1024

    # Agent-loop guardrails
    max_iterations: int = 8
    tool_timeout_seconds: float = 15.0

    # web_fetch tool limits
    fetch_timeout_seconds: float = 10.0
    fetch_max_bytes: int = 2_000_000
    fetch_max_chars: int = 8_000

    # Root dir for per-run sandboxed file workspaces
    workspace_root: str = "./workspaces"

    @property
    def agent_enabled(self) -> bool:
        """Real Claude calls happen only with an API key set and fake mode off."""
        return bool(self.anthropic_api_key) and not self.use_fake_agent


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
