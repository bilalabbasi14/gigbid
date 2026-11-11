"""Central configuration: environment variables (secrets, URLs) + agent/config.yaml (behaviour).

Nothing else in the codebase reads `os.environ` or opens config.yaml directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "agent" / "config.yaml"


class Env(BaseSettings):
    """Secrets and deployment-specific values. Loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "production", "test"] = "development"
    app_secret_key: str = "dev-secret-change-me"  # noqa: S105 (dev default, overridden by .env)
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    token_encryption_key: str = ""
    log_level: str = "INFO"
    pii_masking: bool = True

    database_url: str = "postgresql+psycopg://gigbid:gigbid@localhost:5432/gigbid"
    redis_url: str = "redis://localhost:6379/0"

    marketplace_mode: Literal["gigsim", "upwork_live"] = "gigsim"
    gigsim_base_url: str = "http://localhost:8081"
    gigsim_api_token: str = "dev-token"  # noqa: S105 (dev default, overridden by .env)
    upwork_mcp_url: str = "https://mcp.upwork.com/mcp"
    upwork_oauth_client_id: str = ""
    upwork_oauth_client_secret: str = ""
    upwork_oauth_redirect_uri: str = "http://localhost:8000/auth/upwork/callback"

    mcp_portfolio_url: str = "http://localhost:8101/mcp"
    mcp_marketplace_url: str = "http://localhost:8102/mcp"
    mcp_workspace_url: str = "http://localhost:8103/mcp"
    mcp_bearer_token: str = "dev-mcp-token"  # noqa: S105 (dev default, overridden by .env)
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/x/repos/readonly"
    github_token: str = ""

    model_profile: Literal["open", "paid", "local"] = "open"
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    gemini_api_key: str = ""

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "gigbid"

    reviewer_email: str = "reviewer@gigbid.local"
    reviewer_password: str = "change-me"  # noqa: S105 (dev default, overridden by .env)

    def masked(self) -> dict[str, Any]:
        """Settings with secrets redacted, safe for logs and the settings screen."""
        out: dict[str, Any] = {}
        for k, v in self.model_dump().items():
            out[k] = (
                "***" if any(s in k for s in ("key", "secret", "token", "password")) and v else v
            )
        return out


class ModelProfile(BaseModel):
    small: str
    medium: str
    large: str
    fallback_small: str
    fallback_large: str


class ModelsConfig(BaseModel):
    profile: Literal["open", "paid", "local"] = "open"
    profiles: dict[str, ModelProfile]
    nodes: dict[str, Literal["small", "medium", "large"]]
    embeddings: dict[str, Any]
    reranker: dict[str, Any]
    generation: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    version: int
    policy_version: int
    marketplace: dict[str, Any]
    models: ModelsConfig
    rag: dict[str, Any]
    budgets: dict[str, Any]
    thresholds: dict[str, float]
    pricing: dict[str, Any]
    autonomy: dict[str, Any]
    memory: dict[str, Any]
    guardrails: dict[str, Any]

    def model_for(self, node: str, *, fallback: bool = False, profile: str | None = None) -> str:
        """Resolve `node` -> provider-qualified model name for the active profile."""
        prof = self.models.profiles[profile or self.models.profile]
        tier = self.models.nodes.get(node, "small")
        if fallback:
            return prof.fallback_large if tier == "large" else prof.fallback_small
        return getattr(prof, tier)


@lru_cache(maxsize=1)
def env() -> Env:
    return Env()


@lru_cache(maxsize=1)
def config() -> AgentConfig:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    e = env()
    raw["models"]["profile"] = e.model_profile
    raw["marketplace"]["mode"] = e.marketplace_mode
    return AgentConfig.model_validate(raw)


def reload() -> None:
    """Drop caches (tests, or after editing config.yaml at runtime)."""
    env.cache_clear()
    config.cache_clear()
