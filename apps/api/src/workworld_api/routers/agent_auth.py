from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from workworld_api.dependencies import AppSettings, Database
from workworld_api.security import create_agent_token
from workworld_api.services.agents import AgentError, AgentService

router = APIRouter(prefix="/v1/agent-auth", tags=["agent-auth"])


class AgentTokenRequest(BaseModel):
    credential: str = Field(min_length=30, max_length=300)


@router.post("/token")
def issue_token(body: AgentTokenRequest, db: Database, settings: AppSettings) -> dict[str, object]:
    try:
        agent = AgentService(db).authenticate(body.credential)
    except AgentError as exc:
        raise HTTPException(status_code=401, detail="invalid_agent_credential") from exc
    return {
        "access_token": create_agent_token(agent.id, settings.jwt_secret),
        "token_type": "bearer",
        "expires_in": 300,
        "agent_id": agent.id,
    }
