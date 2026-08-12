import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.models import User
from workworld_api.security import hash_password


class AdminBootstrapError(ValueError):
    pass


def ensure_bootstrap_admin(db: Session, settings: Settings) -> int:
    email = settings.bootstrap_admin_email.strip().lower()
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password is not None
        else ""
    )
    if not email or not password:
        return 0
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        if existing.role != "admin":
            raise AdminBootstrapError("bootstrap_admin_email_belongs_to_non_admin")
        return 0
    db.add(
        User(
            id=f"user_{uuid.uuid4().hex}",
            email=email,
            password_hash=hash_password(password),
            role="admin",
            email_verified=True,
            suspended=False,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    return 1
