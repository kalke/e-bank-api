from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "development"
    log_level: str = "INFO"
    service_name: str = "e-bank-api"

    database_url: str = "postgresql+asyncpg://ebank:ebank@localhost:5432/ebank"
    database_url_test: str = "sqlite+aiosqlite:///:memory:"

    redis_url: str = "redis://localhost:6379/0"
    idempotency_enabled: bool = False
    idempotency_exclude_paths: str = "/health,/ready,/metrics"
    redis_ttl_processing: int = 30
    redis_ttl_completed: int = 86400

    oidc_enabled: bool = True
    oidc_issuer: str = ""
    oidc_audience: str = "e-bank-api"
    oidc_discovery_url: str = ""

    m2m_user_forward_secret: str = ""

    cors_origins: str = ""
    reset_enabled: str | None = None
    legacy_challenge_routes: bool = True

    rate_limit_enabled: bool = False
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    welcome_amount: str = "10000.00"
    welcome_currency: str = "USD"
    account_number_start: int = 1
    max_checking_accounts_per_user: int = 5
    max_transfer_amount: str = "10000.00"
    max_withdraw_amount: str = "10000.00"
    demo_disclaimer: str = (
        "DEMO ONLY — virtual funds for portfolio demonstration. "
        "No real money, no real bank account, no mandatory KYC."
    )

    aws_region: str = "us-east-1"
    secret_id: str = ""
    s3_bank_pdf_bucket: str = ""
    log_format: str = ""

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    @property
    def reset_allowed(self) -> bool:
        if self.reset_enabled is not None:
            return self.reset_enabled.lower() in {"1", "true", "yes", "on"}
        return not self.is_production

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip():
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if self.is_production:
            return ["https://kalke.dev", "https://www.kalke.dev"]
        return [
            "https://kalke.dev",
            "https://www.kalke.dev",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]


@lru_cache
def get_settings() -> Settings:
    # Load once on first settings access (SECRET_ID unset → no-op for local/tests).
    from app.core.secrets import apply_startup_secrets

    apply_startup_secrets()
    return Settings()


settings = get_settings()
