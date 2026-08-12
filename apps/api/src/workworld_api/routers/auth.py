import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from workworld_api.config import Settings, get_settings
from workworld_api.database import get_db
from workworld_api.ids import new_id as _new_id
from workworld_api.models import EmailVerification, RefreshSession, User
from workworld_api.security import (
    create_access_token,
    hash_password,
    opaque_token,
    token_hash,
    verify_password,
)
from workworld_api.services.ledger import LedgerService

router = APIRouter(prefix="/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)
Database = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RefreshCookie = Annotated[str | None, Cookie(alias="workworld_refresh")]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AccessResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email_verified: bool


def _expired(value: datetime, now: datetime) -> bool:
    comparable_now = now if value.tzinfo is not None else now.replace(tzinfo=None)
    return value < comparable_now


def _issue_session(
    user: User, db: Session, response: Response, settings: Settings
) -> AccessResponse:
    raw_refresh = opaque_token()
    now = datetime.now(UTC)
    db.add(
        RefreshSession(
            id=_new_id("session"),
            user_id=user.id,
            token_hash=token_hash(raw_refresh),
            created_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_days),
        )
    )
    db.commit()
    response.set_cookie(
        "workworld_refresh",
        raw_refresh,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=settings.refresh_token_days * 86400,
        path="/v1/auth",
    )
    return AccessResponse(
        access_token=create_access_token(
            user.id, user.role, settings.jwt_secret, settings.access_token_minutes
        ),
        user_id=user.id,
        email_verified=user.email_verified,
    )


@router.post("/register", response_model=AccessResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    response: Response,
    db: Database,
    settings: AppSettings,
) -> AccessResponse:
    now = datetime.now(UTC)
    user = User(
        id=_new_id("user"),
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role="user",
        email_verified=False,
        suspended=False,
        created_at=now,
    )
    raw_verification = opaque_token()
    db.add(user)
    db.add(
        EmailVerification(
            id=_new_id("verify"),
            user_id=user.id,
            token_hash=token_hash(raw_verification),
            expires_at=now + timedelta(hours=24),
        )
    )
    try:
        LedgerService(db).signup_grant(user, commit=False)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="email_already_registered") from exc
    if settings.environment == "development":
        logger.info(
            "development email verification token user_id=%s token=%s", user.id, raw_verification
        )
    return _issue_session(user, db, response, settings)


@router.post("/login", response_model=AccessResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Database,
    settings: AppSettings,
) -> AccessResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(user.password_hash, body.password) or user.suspended:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    return _issue_session(user, db, response, settings)


@router.post("/verify-email")
def verify_email(token: str, db: Database) -> dict[str, bool]:
    verification = db.scalar(
        select(EmailVerification).where(EmailVerification.token_hash == token_hash(token))
    )
    now = datetime.now(UTC)
    if (
        verification is None
        or verification.consumed_at is not None
        or _expired(verification.expires_at, now)
    ):
        raise HTTPException(status_code=400, detail="invalid_or_expired_verification")
    verification.consumed_at = now
    verification.user.email_verified = True
    db.commit()
    return {"verified": True}


@router.post("/refresh", response_model=AccessResponse)
def refresh(
    response: Response,
    db: Database,
    settings: AppSettings,
    workworld_refresh: RefreshCookie = None,
) -> AccessResponse:
    if workworld_refresh is None:
        raise HTTPException(status_code=401, detail="missing_refresh_token")
    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash(workworld_refresh))
    )
    now = datetime.now(UTC)
    if session is None or session.revoked_at is not None or _expired(session.expires_at, now):
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    session.revoked_at = now
    user = db.get(User, session.user_id)
    if user is None or user.suspended:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    return _issue_session(user, db, response, settings)
