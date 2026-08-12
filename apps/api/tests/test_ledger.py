from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.finance_models import LedgerEntry, LedgerTransaction
from workworld_api.market_models import Agent
from workworld_api.models import User
from workworld_api.routers.runs import run_detail
from workworld_api.services.ledger import LedgerError, LedgerService
from workworld_api.task_models import Run, Task


def sqlite_engine_with_foreign_keys() -> Engine:
    engine = create_engine("sqlite+pysqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def add_user(db: Session, user_id: str) -> User:
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    return user


def test_grants_hold_settlement_and_reconstruction_are_balanced() -> None:
    engine = sqlite_engine_with_foreign_keys()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        publisher = add_user(db, "user_publisher")
        provider = add_user(db, "user_provider")
        ledger = LedgerService(db)
        first = ledger.signup_grant(publisher)
        duplicate = ledger.signup_grant(publisher)
        assert duplicate.id == first.id
        assert ledger.balances(publisher.id)["user_available"] == 100_000
        assert first.metadata_json == {"token_policy_version_id": "token_policy_v1"}

        daily = ledger.claim_daily(publisher, date(2026, 8, 10))
        assert ledger.claim_daily(publisher, date(2026, 8, 10)).id == daily.id
        assert ledger.balances(publisher.id)["user_available"] == 110_000

        hold = ledger.hold(publisher.id, "task_1", 4_000)
        db.commit()
        assert ledger.hold(publisher.id, "task_1", 4_000).id == hold.id
        db.commit()
        assert ledger.balances(publisher.id) == {
            "user_available": 106_000,
            "user_held": 4_000,
            "provider_available": 0,
        }

        settlement = ledger.settle(publisher.id, provider.id, "task_1", 3_000)
        db.commit()
        assert settlement.transaction_type == "task_settlement"
        assert ledger.balances(publisher.id)["user_available"] == 107_000
        assert ledger.balances(publisher.id)["user_held"] == 0
        assert ledger.balances(provider.id)["provider_available"] == 3_000

        transaction_ids = list(db.scalars(select(LedgerTransaction.id)))
        for transaction_id in transaction_ids:
            total = db.scalar(
                select(func.sum(LedgerEntry.amount)).where(
                    LedgerEntry.transaction_id == transaction_id
                )
            )
            assert total == 0


def test_overspend_is_rejected_and_history_is_immutable() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db, "user_1")
        ledger = LedgerService(db)
        transaction = ledger.signup_grant(user)
        with pytest.raises(LedgerError, match="insufficient_balance"):
            ledger.hold(user.id, "task_too_large", 100_001)
        db.rollback()
        stored = db.get(LedgerTransaction, transaction.id)
        assert stored is not None
        stored.metadata_json = {"tampered": True}
        with pytest.raises(ValueError, match="historical_financial_record_is_immutable"):
            db.commit()


def test_daily_grant_partially_fills_and_enforces_versioned_balance_cap() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db, "user_cap")
        ledger = LedgerService(db)
        ledger.signup_grant(user)
        ledger.admin_adjust(user.id, 395_000, "cap-setup", "exercise cap")
        transaction = ledger.claim_daily(user, date(2026, 8, 10))
        assert ledger.balances(user.id)["user_available"] == 500_000
        assert sum(
            entry.amount
            for entry in db.query(LedgerEntry).filter_by(transaction_id=transaction.id)
            if entry.amount > 0
        ) == 5_000
        with pytest.raises(LedgerError, match="daily_grant_balance_cap_reached"):
            ledger.claim_daily(user, date(2026, 8, 11))


def test_run_detail_includes_task_referenced_hold_and_settlement() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(UTC)
        publisher = add_user(db, "user_run_publisher")
        provider = add_user(db, "user_run_provider")
        agent = Agent(
            id="agent_run_ledger",
            owner_id=provider.id,
            name="Ledger Agent",
            slug="ledger-agent",
            status="active",
            created_at=now,
        )
        task = Task(
            id="task_run_ledger",
            publisher_id=publisher.id,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Ledger route",
            public_summary="Ledger route",
            input_json={"text": "source", "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={},
            budget_tokens=1_000,
            completion_deadline=now,
            assignment_mode="recommended",
            status="completed",
            created_at=now,
        )
        run = Run(
            id="run_ledger_route",
            task_id=task.id,
            attempt=1,
            offering_version_id="offering_ledger_route_v1",
            agent_id=agent.id,
            state="completed",
            protocol_version="1.0",
            schema_version_id="text.summarize@1.0",
            last_agent_sequence=0,
            next_event_sequence=1,
            clarification_rounds=0,
            rework_count=0,
            offer_expires_at=now,
            completion_deadline=now,
            measured_tokens=250,
            created_at=now,
        )
        db.add_all([agent, task, run])
        db.commit()
        ledger = LedgerService(db)
        ledger.signup_grant(publisher)
        ledger.hold(publisher.id, task.id, task.budget_tokens)
        db.commit()
        ledger.settle(publisher.id, provider.id, task.id, run.measured_tokens)
        db.commit()

        detail = run_detail(run.id, publisher, db)

        assert [row["type"] for row in detail["ledger_transactions"]] == [
            "task_hold",
            "task_settlement",
        ]
