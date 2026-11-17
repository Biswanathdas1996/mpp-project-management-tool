"""Application configuration loaded from environment variables (12-factor)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PMA_", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "Project Management Accelerator"
    api_prefix: str = "/api"

    # --- Database -------------------------------------------------------------
    # postgresql+psycopg://user:pass@host:5432/pma in production; sqlite for local dev/tests.
    database_url: str = "sqlite:///./pma.db"

    # --- Security -------------------------------------------------------------
    secret_key: str = Field(default="change-me-in-production-please-32+chars", min_length=16)
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    max_upload_mb: int = 100

    # Bootstrap admin (created on first start if no users exist)
    bootstrap_admin_email: str = "admin@pma.local"
    bootstrap_admin_password: str = ""  # required in production; random+printed if empty in dev
    bootstrap_tenant_name: str = "Default Organisation"

    # --- OIDC SSO (v1) ----------------------------------------------------------
    oidc_enabled: bool = False
    oidc_issuer: str = ""  # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/auth/oidc/callback"
    oidc_scopes: str = "openid email profile"
    oidc_role_claim: str = "roles"  # claim containing IdP roles/groups
    oidc_admin_values: str = "PMA.Admin"
    oidc_editor_values: str = "PMA.Editor"
    oidc_default_role: str = "super_viewer"
    frontend_url: str = "http://localhost:5173"

    # --- Storage ----------------------------------------------------------------
    storage_backend: Literal["local", "s3", "azure"] = "local"
    storage_local_path: str = "./data/storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = "pma-snapshots"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    azure_connection_string: str = ""
    azure_container: str = "pma-snapshots"

    # --- Queue ------------------------------------------------------------------
    queue_backend: Literal["inline", "rq"] = "inline"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "pma"
    job_timeout_seconds: int = 900

    # --- AI (Ollama behind one provider interface) -------------------------------
    ollama_self_hosted_url: str = "http://localhost:11434"
    ollama_cloud_url: str = "https://ollama.com"
    ollama_cloud_api_key: str = ""
    ai_default_mode: Literal["off", "self_hosted", "cloud"] = "off"
    # DeepSeek V4.1 Flash runs on Ollama Cloud: ":cloud" routes it through a signed-in local Ollama
    # (self_hosted mode); the cloud provider strips the suffix when calling https://ollama.com directly.
    ai_default_model: str = "deepseek-v4.1-flash:cloud"
    # Reasoning ("thinking") for models that support it. Off by default: the reasoning tokens count
    # against num_predict and can truncate the structured JSON answer. None = model default.
    ai_think: bool | None = False
    ai_timeout_seconds: int = 120
    ai_max_input_chars: int = 24000
    ai_daily_call_limit: int = 500
    # First-upload mapping: "confident" approves automatically when the rule-based proposal and the AI
    # agree (or only one is available) and the result passes structural checks; "always" needs only the
    # checks; "off" always waits for an admin in the mapping wizard.
    mapping_auto_approve: Literal["off", "confident", "always"] = "confident"

    # --- Alerts -------------------------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "pma@localhost"
    smtp_tls: bool = True

    # --- Java / MPXJ ------------------------------------------------------------------
    jvm_max_heap: str = "1g"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
