from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from workworld_api.config import Settings, get_settings
from workworld_api.database import get_db
from workworld_api.market_models import Agent
from workworld_api.models import User
from workworld_api.security import decode_access_token, decode_agent_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
Database = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
BearerToken = Annotated[str, Depends(oauth2)]
agent_bearer = HTTPBearer(auto_error=False)


def current_user(token: BearerToken, db: Database, settings: AppSettings) -> User:
    try:
        payload = decode_access_token(token, settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid_access_token") from exc
    user = db.get(User, payload["sub"])
    if user is None or user.suspended:
        raise HTTPException(status_code=401, detail="invalid_access_token")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def current_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return user


CurrentAdmin = Annotated[User, Depends(current_admin)]


def current_agent(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(agent_bearer)],
    db: Database,
    settings: AppSettings,
) -> Agent:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="missing_agent_token")
    try:
        payload = decode_agent_token(credentials.credentials, settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid_agent_token") from exc
    agent = db.get(Agent, payload["sub"])
    if agent is None or agent.status != "active":
        raise HTTPException(status_code=401, detail="invalid_agent_token")
    return agent


CurrentAgent = Annotated[Agent, Depends(current_agent)]
