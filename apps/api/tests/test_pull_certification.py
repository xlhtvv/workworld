import asyncio
from typing import Any, cast

import pytest
from fastapi import WebSocket
from workworld_api.services.pull_certification import (
    PullCertificationRegistry,
    PullCertificationUnavailable,
)


class Socket:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send_json(self, payload: object) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_pull_certification_routes_only_matching_server_attempt() -> None:
    registry = PullCertificationRegistry()
    socket = Socket()
    registry.attach("agent_1", cast(WebSocket, socket))
    pending = asyncio.create_task(
        registry.request(
            "agent_1",
            {"type": "offering.certification", "certification_id": "certification_1"},
        )
    )
    await asyncio.sleep(0)
    assert socket.sent == [
        {"type": "offering.certification", "certification_id": "certification_1"}
    ]
    assert registry.resolve(
        "agent_other",
        {"type": "offering.certification.result", "certification_id": "certification_1"},
    ) is False
    response: dict[str, Any] = {
        "type": "offering.certification.result",
        "certification_id": "certification_1",
    }
    assert registry.resolve("agent_1", response) is True
    assert await pending == response


@pytest.mark.asyncio
async def test_pull_certification_disconnect_fails_pending_attempt() -> None:
    registry = PullCertificationRegistry()
    socket = Socket()
    websocket = cast(WebSocket, socket)
    registry.attach("agent_1", websocket)
    pending = asyncio.create_task(
        registry.request(
            "agent_1",
            {"type": "offering.certification", "certification_id": "certification_1"},
        )
    )
    await asyncio.sleep(0)
    registry.detach("agent_1", websocket)
    with pytest.raises(PullCertificationUnavailable, match="pull_agent_disconnected"):
        await pending


@pytest.mark.asyncio
async def test_pull_certification_requires_live_connection() -> None:
    with pytest.raises(PullCertificationUnavailable, match="pull_agent_not_connected"):
        await PullCertificationRegistry().request(
            "agent_1",
            {"type": "offering.certification", "certification_id": "certification_1"},
        )
