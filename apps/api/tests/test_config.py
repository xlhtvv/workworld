import pytest
from pydantic import ValidationError
from workworld_api.config import Settings


def test_environment_uses_documented_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKWORLD_ENV", "test")
    assert Settings().environment == "test"


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKWORLD_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()


def test_production_rejects_placeholder_secrets() -> None:
    with pytest.raises(ValidationError, match="development placeholders"):
        Settings(environment="production")


def test_production_rejects_insecure_public_object_store_url() -> None:
    with pytest.raises(ValidationError, match="S3_PUBLIC_ENDPOINT_URL must use HTTPS"):
        Settings(
            environment="production",
            jwt_secret="x" * 32,
            push_signing_secret="y" * 32,
            s3_secret_key="z" * 16,
            s3_public_endpoint_url="http://objects.example",
        )


def test_production_rejects_private_push_host_allowlist() -> None:
    with pytest.raises(ValidationError, match="private Push hosts"):
        Settings(
            environment="production",
            jwt_secret="x" * 32,
            push_signing_secret="y" * 32,
            s3_secret_key="z" * 16,
            s3_public_endpoint_url="https://objects.example",
            push_allowed_private_hosts=["push-agent"],
        )


def test_bootstrap_admin_credentials_must_be_complete_and_strong() -> None:
    with pytest.raises(ValidationError, match="are both required"):
        Settings(bootstrap_admin_email="admin@example.com")
    with pytest.raises(ValidationError, match="at least 12 characters"):
        Settings(
            bootstrap_admin_email="admin@example.com",
            bootstrap_admin_password="short",
        )


def test_openai_moderation_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="MODERATION_MODE=openai"):
        Settings(moderation_mode="openai")
