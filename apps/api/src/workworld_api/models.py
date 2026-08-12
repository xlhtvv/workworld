from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    event,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from workworld_api.database import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class ArtifactDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    REJECTED = "rejected"
    ERROR = "error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SchemaDefinition(Base):
    __tablename__ = "schema_definitions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    versions: Mapped[list["SchemaVersion"]] = relationship(back_populates="definition")


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    schema_id: Mapped[str] = mapped_column(ForeignKey("schema_definitions.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    definition: Mapped[SchemaDefinition] = relationship(back_populates="versions")

    __table_args__ = (
        CheckConstraint("status IN ('draft','published','retired')", name="status"),
        Index("uq_schema_versions_schema_version", "schema_id", "version", unique=True),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("direction IN ('input','output')", name="direction"),
        CheckConstraint(
            "scan_status IN ('pending','clean','infected','rejected','error')", name="scan_status"
        ),
        Index("ix_artifacts_task_direction", "task_id", "direction"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(40), index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(1000), unique=True)
    multipart_upload_id: Mapped[str | None] = mapped_column(String(1000))
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(20), default=ScanStatus.PENDING, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactScanResult(Base):
    __tablename__ = "artifact_scan_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    scanner: Mapped[str] = mapped_column(String(100), nullable=False)
    scanner_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    signature: Mapped[str | None] = mapped_column(String(500))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactMeasurement(Base):
    __tablename__ = "artifact_measurements"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    strategy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    values_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@event.listens_for(SchemaVersion, "before_update")
def published_schema_versions_are_immutable(
    mapper: object, connection: Any, target: SchemaVersion
) -> None:
    del mapper
    prior_status = connection.execute(
        select(SchemaVersion.__table__.c.status).where(SchemaVersion.__table__.c.id == target.id)
    ).scalar_one()
    if prior_status == "published":
        raise ValueError("published_schema_version_is_immutable")


@event.listens_for(SchemaVersion, "before_delete")
def published_schema_versions_cannot_be_deleted(
    mapper: object, connection: Any, target: SchemaVersion
) -> None:
    del mapper, connection
    if target.status == "published":
        raise ValueError("published_schema_version_is_immutable")
