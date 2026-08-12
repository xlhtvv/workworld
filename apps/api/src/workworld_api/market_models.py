from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from workworld_api.database import Base
from workworld_api.models import JsonType


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended')", name="status"),
        Index("uq_agents_owner_slug", "owner_id", "slug", unique=True),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent: Mapped[Agent] = relationship()


class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"
    __table_args__ = (
        CheckConstraint("endpoint_type IN ('pull','push')", name="endpoint_type"),
        CheckConstraint("status IN ('pending','verified','failed','revoked')", name="status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_type: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    resolved_addresses: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    challenge_hash: Mapped[str | None] = mapped_column(String(64))
    challenge_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentConnection(Base):
    __tablename__ = "agent_connections"
    __table_args__ = (
        Index("uq_agent_connection_generation", "agent_id", "generation", unique=True),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AgentCapacitySnapshot(Base):
    __tablename__ = "agent_capacity_snapshots"
    __table_args__ = (
        CheckConstraint("status IN ('online','offline','draining')", name="status"),
        CheckConstraint("max_concurrent_runs >= 0", name="nonnegative_max_runs"),
        CheckConstraint("active_runs >= 0", name="nonnegative_active_runs"),
        CheckConstraint("active_runs <= max_concurrent_runs", name="active_within_max"),
        CheckConstraint("queue_capacity >= 0", name="nonnegative_queue"),
        CheckConstraint("estimated_wait_seconds >= 0", name="nonnegative_wait"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    active_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_wait_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    supported_offering_versions: Mapped[list[str]] = mapped_column(
        JsonType, default=list, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Offering(Base):
    __tablename__ = "offerings"
    __table_args__ = (Index("uq_offerings_owner_slug", "owner_id", "slug", unique=True),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    latest_version_id: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OfferingVersion(Base):
    __tablename__ = "offering_versions"
    __table_args__ = (
        Index("uq_offering_versions_number", "offering_id", "version", unique=True),
        CheckConstraint("estimated_tokens_min >= 0", name="nonnegative_min_tokens"),
        CheckConstraint("estimated_tokens_max >= estimated_tokens_min", name="token_range"),
    )

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    offering_id: Mapped[str] = mapped_column(
        ForeignKey("offerings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_id: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    name_i18n: Mapped[dict[str, str]] = mapped_column(JsonType, nullable=False)
    description_i18n: Mapped[dict[str, str]] = mapped_column(JsonType, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    example_artifact_ids: Mapped[list[str]] = mapped_column(
        JsonType, default=list, nullable=False
    )
    risk_disclosure: Mapped[str] = mapped_column(Text, nullable=False)
    output_license: Mapped[str] = mapped_column(String(200), nullable=False)
    sla_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    input_limits: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    estimated_tokens_min: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens_max: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_seconds_min: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_seconds_max: Mapped[int] = mapped_column(Integer, nullable=False)
    auto_apply_policy: Mapped[dict[str, Any]] = mapped_column(
        JsonType, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfferingCertification(Base):
    __tablename__ = "offering_certifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("offering_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_suite_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False)
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[int | None] = mapped_column(Integer)
    log_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookNonce(Base):
    __tablename__ = "webhook_nonces"

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@event.listens_for(OfferingVersion, "before_update")
def published_offering_versions_are_immutable(
    mapper: object, connection: Any, target: OfferingVersion
) -> None:
    del mapper
    prior_status = connection.execute(
        select(OfferingVersion.__table__.c.status).where(
            OfferingVersion.__table__.c.id == target.id
        )
    ).scalar_one()
    if prior_status == "published":
        raise ValueError("published_offering_version_is_immutable")


@event.listens_for(OfferingVersion, "before_delete")
def published_offering_versions_cannot_be_deleted(
    mapper: object, connection: Any, target: OfferingVersion
) -> None:
    del mapper, connection
    if target.status == "published":
        raise ValueError("published_offering_version_is_immutable")


def certification_history_is_immutable(*_: object) -> None:
    raise ValueError("offering_certification_is_immutable")


event.listen(OfferingCertification, "before_update", certification_history_is_immutable)
event.listen(OfferingCertification, "before_delete", certification_history_is_immutable)
