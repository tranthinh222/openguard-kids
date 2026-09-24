from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "OpenGuard Kids Server"
    environment: str = "development"
    database_url: str = "sqlite:///./data/openguard.db"

    jwt_secret: str = "dev-only-change-me-use-at-least-32-bytes"
    policy_hmac_secret: str = "dev-only-policy-secret"

    parent_access_token_expire_minutes: int = 720
    device_access_token_expire_minutes: int = 15
    device_refresh_token_expire_days: int = 30
    enrollment_code_expire_minutes: int = 10

    login_max_failed_attempts: int = 5
    login_lock_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()