from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="WORKWORLD_ENV"
    )
    protocol_version: Literal["1.0"] = Field(
        default="1.0", validation_alias="WORKWORLD_PROTOCOL_VERSION"
    )
    service_name: str = Field(default="workworld-api", validation_alias="WORKWORLD_SERVICE_NAME")
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        validation_alias="WORKWORLD_ALLOWED_ORIGINS",
    )
    database_url: str = Field(
        default="sqlite+pysqlite:///./workworld-dev.db", validation_alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    rate_limit_enabled: bool = Field(default=False, validation_alias="RATE_LIMIT_ENABLED")
    rate_limit_window_seconds: int = Field(
        default=60, validation_alias="RATE_LIMIT_WINDOW_SECONDS", ge=1, le=3600
    )
    rate_limit_auth_requests: int = Field(
        default=120, validation_alias="RATE_LIMIT_AUTH_REQUESTS", ge=1, le=100_000
    )
    rate_limit_mutation_requests: int = Field(
        default=300, validation_alias="RATE_LIMIT_MUTATION_REQUESTS", ge=1, le=100_000
    )
    rate_limit_agent_requests: int = Field(
        default=600, validation_alias="RATE_LIMIT_AGENT_REQUESTS", ge=1, le=100_000
    )
    jwt_secret: str = Field(
        default="development-only-change-me-32-chars", validation_alias="JWT_SECRET", min_length=32
    )
    push_signing_secret: str = Field(
        default="development-push-change-me-32-chars",
        validation_alias="PUSH_SIGNING_SECRET",
        min_length=32,
    )
    access_token_minutes: int = Field(default=15, validation_alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, validation_alias="REFRESH_TOKEN_DAYS")
    s3_endpoint_url: str = Field(
        default="http://localhost:9000", validation_alias="S3_ENDPOINT_URL"
    )
    s3_public_endpoint_url: str = Field(
        default="http://localhost:9000", validation_alias="S3_PUBLIC_ENDPOINT_URL"
    )
    s3_access_key: str = Field(default="workworld", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="change-me", validation_alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="workworld-artifacts", validation_alias="S3_BUCKET")
    clamav_host: str = Field(default="localhost", validation_alias="CLAMAV_HOST")
    clamav_port: int = Field(default=3310, validation_alias="CLAMAV_PORT")
    artifact_max_bytes: int = Field(default=536_870_912, validation_alias="ARTIFACT_MAX_BYTES")
    signed_url_ttl_seconds: int = Field(default=300, validation_alias="SIGNED_URL_TTL_SECONDS")
    push_health_interval_seconds: int = Field(
        default=60, validation_alias="PUSH_HEALTH_INTERVAL_SECONDS", ge=10, le=3600
    )
    push_allowed_private_hosts: list[str] = Field(
        default_factory=list, validation_alias="PUSH_ALLOWED_PRIVATE_HOSTS"
    )
    push_ca_file: str = Field(default="", validation_alias="PUSH_CA_FILE")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_evaluation_model: str = Field(
        default="gpt-5-mini", validation_alias="OPENAI_EVALUATION_MODEL"
    )
    evaluation_multimodal_max_bytes: int = Field(
        default=20 * 1024 * 1024,
        validation_alias="EVALUATION_MULTIMODAL_MAX_BYTES",
        gt=0,
        le=100 * 1024 * 1024,
    )
    evaluation_mode: Literal["mock", "openai"] = Field(
        default="mock", validation_alias="EVALUATION_MODE"
    )
    moderation_mode: Literal["local", "openai"] = Field(
        default="local", validation_alias="MODERATION_MODE"
    )
    openai_moderation_model: str = Field(
        default="omni-moderation-latest", validation_alias="OPENAI_MODERATION_MODEL"
    )
    openai_transcription_model: str = Field(
        default="gpt-4o-mini-transcribe", validation_alias="OPENAI_TRANSCRIPTION_MODEL"
    )
    moderation_media_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        validation_alias="MODERATION_MEDIA_MAX_BYTES",
        gt=0,
        le=100 * 1024 * 1024,
    )
    bootstrap_admin_email: str = Field(
        default="", validation_alias="BOOTSTRAP_ADMIN_EMAIL"
    )
    bootstrap_admin_password: SecretStr | None = Field(
        default=None, validation_alias="BOOTSTRAP_ADMIN_PASSWORD"
    )

    @model_validator(mode="after")
    def production_secrets_must_be_explicit(self) -> Self:
        if self.environment == "production" and (
            "change-me" in self.jwt_secret
            or "change-me" in self.push_signing_secret
            or "change-me" in self.s3_secret_key
        ):
            raise ValueError("production secrets must not use development placeholders")
        if self.environment == "production" and not self.s3_public_endpoint_url.startswith(
            "https://"
        ):
            raise ValueError("S3_PUBLIC_ENDPOINT_URL must use HTTPS in production")
        if self.environment == "production" and self.push_allowed_private_hosts:
            raise ValueError("private Push hosts are forbidden in production")
        if self.environment == "production" and not self.rate_limit_enabled:
            raise ValueError("RATE_LIMIT_ENABLED must be true in production")
        if self.evaluation_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when EVALUATION_MODE=openai")
        if self.moderation_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when MODERATION_MODE=openai")
        admin_email = self.bootstrap_admin_email.strip()
        admin_password = (
            self.bootstrap_admin_password.get_secret_value()
            if self.bootstrap_admin_password is not None
            else ""
        )
        if bool(admin_email) != bool(admin_password):
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are both required")
        if admin_password and len(admin_password) < 12:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
