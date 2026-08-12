from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from workworld_api.database import Base
from workworld_api.models import JsonType


class MeteringFormulaVersion(Base):
    __tablename__ = "metering_formula_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TokenPolicyVersion(Base):
    __tablename__ = "token_policy_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualityRubricVersion(Base):
    __tablename__ = "quality_rubric_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    schema_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("uq_quality_rubric_schema_version", "schema_id", "version", unique=True),
    )


class QualityEvaluation(Base):
    __tablename__ = "quality_evaluations"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_version_id: Mapped[str] = mapped_column(
        ForeignKey("quality_rubric_versions.id"), nullable=False
    )
    evaluation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, nullable=False)
    issues_json: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("uq_quality_evaluation_round", "run_id", "round_number", unique=True),
        CheckConstraint("quality_score >= 0 AND quality_score <= 100", name="quality_score"),
    )


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    account_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("amount <> 0", name="nonzero_amount"),
        Index("uq_ledger_entry_account", "transaction_id", "account_id", unique=True),
    )


class DailyGrantClaim(Base):
    __tablename__ = "daily_grant_claims"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("uq_daily_grant", "user_id", "claim_date", unique=True),)


IMMUTABLE_TYPES = (
    MeteringFormulaVersion,
    TokenPolicyVersion,
    QualityRubricVersion,
    QualityEvaluation,
    LedgerTransaction,
    LedgerEntry,
)


def _immutable(*_: object) -> None:
    raise ValueError("historical_financial_record_is_immutable")


for immutable_type in IMMUTABLE_TYPES:
    event.listen(immutable_type, "before_update", _immutable)
    event.listen(immutable_type, "before_delete", _immutable)
