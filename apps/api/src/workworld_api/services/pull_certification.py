import asyncio
from typing import Any

from fastapi import WebSocket


class PullCertificationUnavailable(RuntimeError):
    pass


class PullCertificationRegistry:
    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}
        self._pending: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}

    def attach(self, agent_id: str, socket: WebSocket) -> None:
        self._sockets[agent_id] = socket

    def detach(self, agent_id: str, socket: WebSocket) -> None:
        if self._sockets.get(agent_id) is socket:
            self._sockets.pop(agent_id, None)
            for key, future in list(self._pending.items()):
                if key[0] == agent_id and not future.done():
                    future.set_exception(PullCertificationUnavailable("pull_agent_disconnected"))

    async def request(
        self, agent_id: str, payload: object, timeout_seconds: float = 120
    ) -> dict[str, Any]:
        socket = self._sockets.get(agent_id)
        if socket is None or not isinstance(payload, dict):
            raise PullCertificationUnavailable("pull_agent_not_connected")
        certification_id = str(payload.get("certification_id", ""))
        if not certification_id:
            raise PullCertificationUnavailable("certification_id_missing")
        key = (agent_id, certification_id)
        if key in self._pending:
            raise PullCertificationUnavailable("certification_already_running")
        future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            await socket.send_json(payload)
            return await asyncio.wait_for(future, timeout_seconds)
        finally:
            self._pending.pop(key, None)

    def resolve(self, agent_id: str, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        certification_id = payload.get("certification_id")
        if not isinstance(certification_id, str):
            return False
        future = self._pending.get((agent_id, certification_id))
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True


pull_certifications = PullCertificationRegistry()
