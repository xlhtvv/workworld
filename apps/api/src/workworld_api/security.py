import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str, role: str, secret: str, minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    payload: dict[str, Any] = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def create_agent_token(agent_id: str, secret: str, minutes: int = 5) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": agent_id,
            "type": "agent",
            "jti": secrets.token_hex(16),
            "iat": now,
            "exp": now + timedelta(minutes=minutes),
        },
        secret,
        algorithm="HS256",
    )


def decode_agent_token(token: str, secret: str) -> dict[str, Any]:
    payload: dict[str, Any] = jwt.decode(token, secret, algorithms=["HS256"])
    if payload.get("type") != "agent":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
