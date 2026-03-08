"""Application configuration loaded from environment variables."""

import logging
import secrets

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Sentinel so we can detect whether SECRET_KEY was set by the operator
_GENERATED_SENTINEL = "__generated__"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Ayntec Shipping Notifier"
    app_url: str = "http://localhost:8000"
    secret_key: str = _GENERATED_SENTINEL
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # OIDC / Authentik
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_discovery_url: str = ""
    # e.g. https://auth.example.com/application/o/ayntec-notifier/.well-known/openid-configuration

    # Poll interval (seconds)
    poll_interval_seconds: int = 300  # 5 minutes

    # Ayntec shipping dashboard URL — scraped for shipped order-number ranges
    ayntec_dashboard_url: str = "https://www.ayntec.com/pages/shipment-dashboard"

    # GitHub repository URL (shown on landing page)
    github_repo_url: str = "https://github.com/Biohive/ayntec-shipping-notification"

    # SMTP (leave smtp_host blank to disable email notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_not_be_empty(cls, v: str) -> str:
        if not v or v == _GENERATED_SENTINEL:
            generated = secrets.token_hex(32)
            logger.warning(
                "SECRET_KEY is not set — a random key was generated. "
                "All sessions will be invalidated on restart. "
                "Set SECRET_KEY in your .env file to persist sessions."
            )
            return generated
        return v


settings = Settings()
