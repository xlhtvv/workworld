import asyncio
import hashlib
import json
import logging
import re
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import websockets
from websockets.typing import Subprotocol

from workworld_sdk.protocol import Envelope

AgentResponse = Envelope | dict[str, Any]
Handler = Callable[[dict[str, Any]], Awaitable[list[AgentResponse]]]
logger = logging.getLogger("workworld_sdk")


def _redact(value: str) -> str:
    return re.sub(r"(?:wwa_[^.\s]+\.)[^\s]+", r"\1[REDACTED]", value)


class AgentClient:
    def __init__(self, api_url: str, credential: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.credential = credential
        self.agent_id: str | None = None
        self.token: str | None = None

    @classmethod
    def provision(
        cls,
        api_url: str,
        human_access_token: str,
        *,
        name: str,
        endpoint_type: str,
        slug: str | None = None,
        endpoint_url: str | None = None,
    ) -> "AgentClient":
        if endpoint_type not in {"pull", "push"}:
            raise ValueError("endpoint_type_invalid")
        if endpoint_type == "push" and not endpoint_url:
            raise ValueError("push_endpoint_url_required")
        base = api_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {human_access_token}",
            "Content-Type": "application/json",
        }

        def post(path: str, document: dict[str, Any]) -> dict[str, Any]:
            request = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(document).encode(),
                method="POST",
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return dict(json.load(response))

        agent = post("/v1/agents", {"name": name, "slug": slug})
        agent_id = str(agent["id"])
        credential = post(f"/v1/agents/{agent_id}/credentials", {})
        post(
            f"/v1/agents/{agent_id}/endpoints",
            {"endpoint_type": endpoint_type, "url": endpoint_url},
        )
        client = cls(base, str(credential["credential"]))
        client.agent_id = agent_id
        return client

    def authenticate(self) -> str:
        request = urllib.request.Request(
            f"{self.api_url}/v1/agent-auth/token",
            data=json.dumps({"credential": self.credential}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            document = json.load(response)
        self.agent_id = str(document["agent_id"])
        self.token = str(document["access_token"])
        return self.token

    def callback(self, envelope: Envelope) -> dict[str, Any]:
        token = self.token or self.authenticate()
        request = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/events",
            data=json.dumps(envelope.as_dict()).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return dict(json.load(response))

    def update_capacity(
        self,
        *,
        status: str,
        max_concurrent_runs: int,
        active_runs: int,
        queue_capacity: int,
        estimated_wait_seconds: int,
        supported_offering_versions: list[str],
    ) -> None:
        if status not in {"online", "offline", "draining"}:
            raise ValueError("capacity_status_invalid")
        token = self.token or self.authenticate()
        request = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/capacity",
            data=json.dumps(
                {
                    "status": status,
                    "max_concurrent_runs": max_concurrent_runs,
                    "active_runs": active_runs,
                    "queue_capacity": queue_capacity,
                    "estimated_wait_seconds": estimated_wait_seconds,
                    "supported_offering_versions": supported_offering_versions,
                }
            ).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 204:
                raise RuntimeError("agent_capacity_update_failed")

    def download_artifact(self, artifact_id: str) -> bytes:
        token = self.token or self.authenticate()
        request = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/artifacts/{artifact_id}/download",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            url = str(json.load(response)["url"])
        with urllib.request.urlopen(url, timeout=60) as response:
            return cast(bytes, response.read())

    def upload_artifact(
        self, task_id: str | None, path: str | Path, *, kind: str, mime_type: str
    ) -> dict[str, Any]:
        token = self.token or self.authenticate()
        payload = Path(path).read_bytes()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        begin = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/artifacts/uploads",
            data=json.dumps(
                {
                    "original_name": Path(path).name,
                    "kind": kind,
                    "direction": "output",
                    "mime_type": mime_type,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "task_id": task_id,
                }
            ).encode(),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(begin, timeout=30) as response:
            artifact = dict(json.load(response))
        artifact_id = str(artifact["id"])
        sign = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/artifacts/{artifact_id}/parts/1",
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(sign, timeout=30) as response:
            upload_url = str(json.load(response)["url"])
        put = urllib.request.Request(upload_url, data=payload, method="PUT")
        with urllib.request.urlopen(put, timeout=120) as response:
            etag = response.headers.get("ETag", "").strip('"')
        complete = urllib.request.Request(
            f"{self.api_url}/v1/agent-callbacks/artifacts/{artifact_id}/complete",
            data=json.dumps({"parts": [{"PartNumber": 1, "ETag": etag}]}).encode(),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(complete, timeout=180) as response:
            return dict(json.load(response))


class PullAgent:
    def __init__(self, client: AgentClient, handler: Handler) -> None:
        self.client = client
        self.handler = handler
        self._stopped = False

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        delay = 1
        acknowledged_sequence = 0
        while not self._stopped:
            token = self.client.authenticate()
            ws_url = self.client.api_url.replace("https://", "wss://").replace(
                "http://", "ws://"
            )
            try:
                async with websockets.connect(
                    f"{ws_url}/v1/agents/connect",
                    additional_headers={"Authorization": f"Bearer {token}"},
                    subprotocols=[Subprotocol("workworld.v1")],
                    max_size=2 * 1024 * 1024,
                ) as socket:
                    delay = 1
                    async for raw in socket:
                        message = json.loads(raw)
                        yield message
                        sequence = message.get("sequence")
                        if isinstance(sequence, int):
                            acknowledged_sequence = max(acknowledged_sequence, sequence)
                        responses = await self.handler(message)
                        for response in responses:
                            document = (
                                response.as_dict()
                                if isinstance(response, Envelope)
                                else response
                            )
                            await socket.send(json.dumps(document))
                        if message.get("type") != "agent.registered":
                            heartbeat = Envelope.create(
                                str(self.client.agent_id),
                                "run_system",
                                "agent.heartbeat",
                                1,
                                {
                                    "acknowledged_sequence": acknowledged_sequence,
                                    "acknowledged_message_ids": [message.get("message_id", "")],
                                },
                            )
                            await socket.send(json.dumps(heartbeat.as_dict()))
            except (OSError, websockets.ConnectionClosed) as exc:
                logger.warning("pull connection interrupted: %s", _redact(str(exc)))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def run_forever(self) -> None:
        async for _message in self.messages():
            pass

    def stop(self) -> None:
        self._stopped = True
