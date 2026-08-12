import asyncio
import json
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from workworld_api.config import get_settings
from workworld_api.database import session_factory
from workworld_api.schema_catalog import CATALOG_PATH
from workworld_api.security import decode_agent_token
from workworld_api.services.agents import AgentError, AgentService
from workworld_api.services.connections import ConnectionError, PullConnectionService
from workworld_api.services.protocol import ProtocolError, ProtocolService
from workworld_api.services.pull_certification import pull_certifications
from workworld_api.services.run_control import RunControlService

router = APIRouter(tags=["agent-pull"])
PROTOCOL_SCHEMA_PATH = CATALOG_PATH.parents[1] / "protocol" / "envelope.schema.json"
PROTOCOL_VALIDATOR = Draft202012Validator(
    json.loads(PROTOCOL_SCHEMA_PATH.read_text(encoding="utf-8"))
)


def message(message_type: str, agent_id: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "idempotency_key": f"system:{uuid.uuid4()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "agent_id": agent_id,
        "run_id": "run_system",
        "type": message_type,
        "sequence": 1,
        "payload": payload,
    }


async def deliver_pending(
    websocket: WebSocket, protocol: ProtocolService, agent_id: str, *, force: bool = False
) -> None:
    for _outbox, event in protocol.pending_outbox(agent_id, force=force):
        await websocket.send_json(protocol.event_envelope(event, agent_id))


@router.websocket("/v1/agents/connect")
async def connect(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        await websocket.close(code=4401, reason="missing_agent_token")
        return
    try:
        claims = decode_agent_token(
            authorization.removeprefix("Bearer "), get_settings().jwt_secret
        )
    except jwt.InvalidTokenError:
        await websocket.close(code=4401, reason="invalid_agent_token")
        return
    agent_id = str(claims["sub"])
    with session_factory()() as db:
        service = PullConnectionService(db)
        protocol = ProtocolService(db)
        try:
            connection = service.connect(agent_id)
        except ConnectionError:
            await websocket.close(code=4403, reason="agent_unavailable")
            return
        await websocket.accept(subprotocol="workworld.v1")
        pull_certifications.attach(agent_id, websocket)
        await websocket.send_json(
            message(
                "agent.registered",
                agent_id,
                {
                    "connection_id": connection.id,
                    "generation": connection.generation,
                    "resume_from_sequence": connection.acknowledged_sequence,
                },
            )
        )
        RunControlService(db).recover_agent(agent_id)
        await deliver_pending(websocket, protocol, agent_id, force=True)
        try:
            while True:
                try:
                    incoming = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                except TimeoutError:
                    await deliver_pending(websocket, protocol, agent_id)
                    continue
                if incoming.get("type") == "offering.certification.result":
                    if not pull_certifications.resolve(agent_id, incoming):
                        await websocket.send_json(
                            message(
                                "protocol.error",
                                agent_id,
                                {"code": "certification_not_pending"},
                            )
                        )
                    continue
                errors = list(PROTOCOL_VALIDATOR.iter_errors(incoming))
                if errors:
                    await websocket.send_json(
                        message("protocol.error", agent_id, {"code": "invalid_message"})
                    )
                    continue
                if incoming["agent_id"] != agent_id:
                    await websocket.close(code=4403, reason="agent_identity_mismatch")
                    return
                if incoming["type"] == "agent.heartbeat":
                    acknowledged = int(incoming["payload"].get("acknowledged_sequence", 0))
                    service.heartbeat(connection.id, acknowledged)
                    event_ids = incoming["payload"].get("acknowledged_event_ids", [])
                    message_ids = incoming["payload"].get("acknowledged_message_ids", [])
                    if isinstance(event_ids, list):
                        acknowledgements = [str(item) for item in event_ids]
                        if isinstance(message_ids, list):
                            acknowledgements.extend(str(item) for item in message_ids)
                        protocol.acknowledge_outbox(agent_id, acknowledgements)
                elif incoming["type"] == "agent.capacity_updated":
                    payload = incoming["payload"]
                    agent = AgentService(db).get_active(agent_id)
                    AgentService(db).capacity(
                        agent,
                        status=str(payload["status"]),
                        max_concurrent_runs=int(payload["max_concurrent_runs"]),
                        active_runs=int(payload["active_runs"]),
                        queue_capacity=int(payload["queue_capacity"]),
                        estimated_wait_seconds=int(payload["estimated_wait_seconds"]),
                        supported_offering_versions=[
                            str(item) for item in payload["supported_offering_versions"]
                        ],
                    )
                else:
                    try:
                        protocol.ingest_agent_message(agent_id, incoming)
                    except ProtocolError as exc:
                        db.rollback()
                        await websocket.send_json(
                            message("protocol.error", agent_id, {"code": str(exc)})
                        )
        except (AgentError, ConnectionError, KeyError, TypeError, ValueError) as exc:
            db.rollback()
            await websocket.close(code=4400, reason=str(exc))
        except WebSocketDisconnect:
            service.disconnect(connection.id)
        finally:
            pull_certifications.detach(agent_id, websocket)
