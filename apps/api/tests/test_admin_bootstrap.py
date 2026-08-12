from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.models import User
from workworld_api.security import verify_password
from workworld_api.services.admin_bootstrap import AdminBootstrapError, ensure_bootstrap_admin


def test_bootstrap_admin_is_hashed_verified_and_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    settings = Settings(
        bootstrap_admin_email="Admin@Example.com",
        bootstrap_admin_password="correct horse battery staple",
    )
    with Session(engine) as db:
        assert ensure_bootstrap_admin(db, settings) == 1
        admin = db.query(User).filter_by(email="admin@example.com").one()
        assert admin.role == "admin"
        assert admin.email_verified is True
        assert admin.password_hash != "correct horse battery staple"
        assert verify_password(admin.password_hash, "correct horse battery staple")
        assert ensure_bootstrap_admin(db, settings) == 0


def test_bootstrap_refuses_to_promote_an_existing_user() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            User(
                id="user_existing",
                email="admin@example.com",
                password_hash="existing",
                role="user",
                email_verified=True,
                suspended=False,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        settings = Settings(
            bootstrap_admin_email="admin@example.com",
            bootstrap_admin_password="correct horse battery staple",
        )
        with pytest.raises(AdminBootstrapError, match="belongs_to_non_admin"):
            ensure_bootstrap_admin(db, settings)
