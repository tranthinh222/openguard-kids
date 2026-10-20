from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

class Settings(BaseSettings):
    app_name: str = "OpenGuard Kids Server"
    environment: str = "development"
    database_url: str = "sqlite:///./data/openguard.db"

    jwt_secret: str = "dev-only-change-me-use-at-least-32-bytes"
    policy_hmac_secret: str = "dev-only-policy-secret"
    data_encryption_key: str = ""

    parent_access_token_expire_minutes: int = 720
    device_access_token_expire_minutes: int = 15
    device_refresh_token_expire_days: int = 30
    enrollment_code_expire_minutes: int = 10
    agent_clock_drift_threshold_sec: float = Field(default=120, gt=0, allow_inf_nan=False)
    report_timezone_offset_minutes: int = Field(default=420, ge=-720, le=840)

    web_session_expire_hours: int = 12
    web_cookie_secure: bool = False
    allowed_hosts: list[str] = Field(default_factory=lambda: ['*'])
    asset_version: str = 'w04'
    max_request_bytes: int = Field(default=1048576, ge=1024, le=16777216)
    auth_requests_per_minute: int = Field(default=30, ge=1)
    api_requests_per_minute: int = Field(default=600, ge=1)
    rate_limit_enabled: bool = True
    retention_interval_sec: int = Field(default=86400, ge=60)
    retention_retry_sec: int = Field(default=3600, ge=1)
    websocket_auth_interval_sec: int = Field(default=30, ge=1, le=60)
    websocket_max_message_bytes: int = Field(default=4096, ge=256, le=65536)
    websocket_messages_per_minute: int = Field(default=120, ge=20)
    log_level: str = 'INFO'

    @model_validator(mode='after')
    def deployment_settings(self):
        import base64
        try:
            key = base64.b64decode(self.data_encryption_key, validate=True)
        except ValueError as exc:
            raise ValueError("DATA_ENCRYPTION_KEY must be base64 encoded") from exc
        if key and len(key) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY must encode 32 random bytes")
        if self.environment.lower() not in {'development', 'test', 'staging', 'production'}:
            raise ValueError('Unsupported ENVIRONMENT')
        if self.log_level.upper() not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
            raise ValueError('Unsupported LOG_LEVEL')
        for name in ('parent_access_token_expire_minutes', 'device_access_token_expire_minutes',
                     'device_refresh_token_expire_days', 'enrollment_code_expire_minutes',
                     'web_session_expire_hours', 'login_max_failed_attempts', 'login_lock_minutes'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        if self.environment.lower() in {'production', 'staging'}:
            if not key or key == bytes(32):
                raise ValueError("Production requires a private DATA_ENCRYPTION_KEY")
            for name in ('jwt_secret', 'policy_hmac_secret'):
                value = getattr(self, name)
                if len(value) < 32 or value.startswith(('dev-only', 'replace-with')):
                    raise ValueError(f'{name} must be a non-placeholder secret of at least 32 characters')
            if self.jwt_secret == self.policy_hmac_secret:
                raise ValueError('JWT and policy signing secrets must be different')
            if not self.web_cookie_secure or not self.allowed_hosts or '*' in self.allowed_hosts:
                raise ValueError('Staging/production requires secure cookies and explicit ALLOWED_HOSTS')
        return self

    login_max_failed_attempts: int = 5
    login_lock_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
