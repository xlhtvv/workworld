from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workworld_api.ids import new_id
from workworld_api.market_models import Agent, AgentConnection, AgentEndpoint


class ConnectionError(ValueError):
    pass


class PullConnectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def connect(self, agent_id: str) -> AgentConnection:
        agent = self.db.scalar(select(Agent).where(Agent.id == agent_id).with_for_update())
        if agent is None or agent.status != "active":
            raise ConnectionError("agent_unavailable")
        endpoint = self.db.scalar(
            select(AgentEndpoint).where(
                AgentEndpoint.agent_id == agent_id,
                AgentEndpoint.endpoint_type == "pull",
                AgentEndpoint.status.in_(["pending", "verified"]),
            )
        )
        if endpoint is None:
            raise ConnectionError("pull_endpoint_not_registered")
        now = datetime.now(UTC)
        active = self.db.scalars(
            select(AgentConnection).where(
                AgentConnection.agent_id == agent_id,
                AgentConnection.disconnected_at.is_(None),
            )
        )
        for connection in active:
            connection.disconnected_at = now
        generation = (
            self.db.scalar(
                select(func.max(AgentConnection.generation)).where(
                    AgentConnection.agent_id == agent_id
                )
            )
            or 0
        ) + 1
        acknowledged_sequence = (
            self.db.scalar(
                select(func.max(AgentConnection.acknowledged_sequence)).where(
                    AgentConnection.agent_id == agent_id
                )
            )
            or 0
        )
        connection = AgentConnection(
            id=new_id("connection"),
            agent_id=agent_id,
            generation=generation,
            connected_at=now,
            heartbeat_at=now,
            acknowledged_sequence=acknowledged_sequence,
        )
        endpoint.status = "verified"
        endpoint.verified_at = endpoint.verified_at or now
        self.db.add(connection)
        self.db.commit()
        return connection

    def heartbeat(self, connection_id: str, acknowledged_sequence: int) -> None:
        connection = self.db.get(AgentConnection, connection_id)
        if connection is None or connection.disconnected_at is not None:
            raise ConnectionError("connection_not_active")
        if acknowledged_sequence < connection.acknowledged_sequence:
            raise ConnectionError("acknowledgement_regressed")
        connection.heartbeat_at = datetime.now(UTC)
        connection.acknowledged_sequence = acknowledged_sequence
        self.db.commit()

    def disconnect(self, connection_id: str) -> None:
        connection = self.db.get(AgentConnection, connection_id)
        if connection is not None and connection.disconnected_at is None:
            connection.disconnected_at = datetime.now(UTC)
            self.db.commit()
