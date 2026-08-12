import logging
import re
from collections.abc import Generator
from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.models import RefreshSession, User
from workworld_api.routers.auth import (
    LoginRequest,
    RegisterRequest,
    login,
    refresh,
    register,
    verify_email,
)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def refresh_cookie(response: Response) -> str:
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie["workworld_refresh"].value


def test_register_verify_login_and_rotating_refresh(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings(environment="development")
    caplog.set_level(logging.INFO, logger="workworld_api.routers.auth")
    first_response = Response()
    registered = register(
        RegisterRequest(email="Publisher@Example.com", password="correct horse battery staple"),
        first_response,
        db,
        settings,
    )
    assert registered.email_verified is False
    assert refresh_cookie(first_response)

    token_match = re.search(r"token=(\S+)", caplog.text)
    assert token_match is not None
    assert verify_email(token_match.group(1), db) == {"verified": True}

    login_response = Response()
    logged_in = login(
        LoginRequest(email="publisher@example.com", password="correct horse battery staple"),
        login_response,
        db,
        settings,
    )
    assert logged_in.email_verified is True

    refresh_response = Response()
    refreshed = refresh(
        refresh_response,
        db,
        settings,
        refresh_cookie(login_response),
    )
    assert refreshed.access_token != logged_in.access_token
    sessions = db.query(RefreshSession).all()
    assert len(sessions) == 3
    assert sum(item.revoked_at is not None for item in sessions) == 1


def test_duplicate_email_and_bad_password_are_generic(db: Session) -> None:
    settings = Settings(environment="test")
    payload = RegisterRequest(email="same@example.com", password="correct horse battery staple")
    register(payload, Response(), db, settings)
    with pytest.raises(HTTPException) as duplicate:
        register(payload, Response(), db, settings)
    assert duplicate.value.status_code == 409

    with pytest.raises(HTTPException) as bad_login:
        login(
            LoginRequest(email="same@example.com", password="completely wrong"),
            Response(),
            db,
            settings,
        )
    assert bad_login.value.status_code == 401
    assert bad_login.value.detail == "invalid_credentials"
    assert db.query(User).count() == 1
