"""Runtime configuration, read once from the environment or `.env`.

Every secret is a `SecretStr`, so logging the settings object (or an exception that renders
it) prints `**********` instead of a key. Nothing here has a hardcoded credential; a missing
key degrades a feature (no Groq key -> the router falls back to Gemini, no DATABASE_URL ->
the in-memory store) rather than crashing import.
"""

from __future__ import annotations

from functools import lru_cache

from llm_kit import Settings as LLMSettings
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- storage ------------------------------------------------------------------
    database_url: SecretStr | None = None

    # --- GitHub -------------------------------------------------------------------
    # Server token: 5,000 req/h instead of 60. A per-run user token overrides it and is
    # never persisted (see collect.github and api.routes).
    github_token: SecretStr | None = None

    # --- model providers (handed to llm-kit explicitly, see llm_settings) ---------
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"

    # --- API ----------------------------------------------------------------------
    cron_secret: SecretStr | None = None
    # Comma-separated list of origins allowed by CORS (the Next.js app).
    web_origin: str = "http://localhost:3000,http://localhost:3600"
    port: int = 7860
    runs_per_hour_per_ip: int = 10
    # Behind Hugging Face Spaces / Render the client IP arrives in X-Forwarded-For. Only
    # trust that header when a proxy we control sets it; otherwise anyone can spoof it.
    trust_proxy_headers: bool = False
    # Salt for hashing client IPs before they are stored (we keep a hash, not the IP).
    ip_hash_salt: SecretStr = SecretStr("changelog-forge")

    # --- run dispatch (see docs/decisions/0002-hosting.md and dispatch.py) ----------
    # Vercel sets VERCEL=1. There are no background workers there, so without QStash the
    # client is told to call POST /api/runs/{id}/process itself.
    vercel: bool = False
    public_api_url: str | None = None  # e.g. https://changelog-forge-api.vercel.app
    qstash_url: str = "https://qstash.upstash.io"
    qstash_token: SecretStr | None = None
    qstash_current_signing_key: SecretStr | None = None
    qstash_next_signing_key: SecretStr | None = None
    process_time_budget_s: float = 240.0

    # --- pipeline -----------------------------------------------------------------
    max_commits: int = Field(default=400, ge=1, le=2000)
    max_usd_per_run: float | None = None  # None -> routing.toml budget

    # --- observability (optional) ---------------------------------------------------
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    log_level: str = "INFO"

    @property
    def web_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origin.split(",") if origin.strip()]

    def llm_settings(self) -> LLMSettings:
        """llm-kit settings built from *this* project's config.

        llm-kit's own `Settings()` reads the journey workspace `.env`. Passing every field
        explicitly makes this repository's `.env` (or the container environment) the only
        source of keys, which is what a standalone deploy needs.
        """
        return LLMSettings(
            gemini_api_key=self.gemini_api_key,
            groq_api_key=self.groq_api_key,
            openrouter_api_key=self.openrouter_api_key,
            ollama_base_url=self.ollama_base_url,
        )

    def has_key(self, provider: str) -> bool:
        secret = getattr(self, f"{provider}_api_key", None)
        return bool(secret and secret.get_secret_value())


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
