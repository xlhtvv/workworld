from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from workworld_api.database import Base
from workworld_api.models import JsonType


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("assignment_mode IN ('recommended','open_call')", name="assignment_mode"),
        CheckConstraint("budget_tokens > 0", name="positive_budget"),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    publisher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    schema_id: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    public_summary: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    field_visibility: Mapped[dict[str, str]] = mapped_column(JsonType, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False)
    acceptance_rules: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    budget_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    recruitment_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assignment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskInputVersion(Base):
    __tablename__ = "task_input_versions"
    __table_args__ = (Index("uq_task_input_version", "task_id", "version", unique=True),)
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"
    __table_args__ = (
        CheckConstraint("direction IN ('input','output')", name="direction"),
        CheckConstraint("visibility IN ('public','applicants','winner')", name="visibility"),
        Index("uq_task_artifact", "task_id", "artifact_id", unique=True),
        Index("ix_task_artifacts_task_direction", "task_id", "direction"),
    )
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index("uq_recommendation_candidate", "task_id", "offering_version_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("offering_versions.id"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("uq_application_candidate", "task_id", "offering_version_id", unique=True),
        CheckConstraint("estimated_tokens_min >= 0", name="nonnegative_min_tokens"),
        CheckConstraint("estimated_tokens_max >= estimated_tokens_min", name="token_range"),
    )
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("offering_versions.id"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    estimated_tokens_min: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens_max: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_completion_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("uq_run_attempt", "task_id", "attempt", unique=True),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("offering_versions.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    metering_formula_version_id: Mapped[str | None] = mapped_column(String(80))
    quality_rubric_version_id: Mapped[str | None] = mapped_column(String(80))
    last_agent_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_event_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    clarification_rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rework_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    measured_tokens: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[int | None] = mapped_column(Integer)
    offer_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunSlotReservation(Base):
    __tablename__ = "run_slot_reservations"
    __table_args__ = (Index("ix_active_agent_slots", "agent_id", "status"),)
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        Index("uq_run_event_sequence", "run_id", "sequence", unique=True),
        Index("uq_run_event_idempotency", "run_id", "idempotency_key", unique=True),
    )
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_sequence: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(50))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClarificationRequest(Base):
    __tablename__ = "clarification_requests"
    __table_args__ = (Index("uq_clarification_round", "run_id", "round_number", unique=True),)
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_schema: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    default_answer: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    blocking: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answer_json: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BudgetExtensionRequest(Base):
    __tablename__ = "budget_extension_requests"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    requested_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReworkRequest(Base):
    __tablename__ = "rework_requests"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id"), nullable=False, unique=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_rule_refs: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProtocolOutbox(Base):
    __tablename__ = "protocol_outbox"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_event_id: Mapped[str] = mapped_column(
        ForeignKey("run_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
