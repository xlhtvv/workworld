import hashlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket
from PIL import Image


def load_media_example() -> Any:
    root = Path(__file__).parents[3]
    path = root / "examples" / "python-media-echo-agent" / "agent.py"
    spec = importlib.util.spec_from_file_location("workworld_media_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_media_agent_reuses_artifact_and_envelopes_for_replayed_offer() -> None:
    example = load_media_example()
    source = io.BytesIO()
    Image.new("RGB", (64, 64), color="blue").save(source, format="PNG")

    class Client:
        downloads = 0
        uploads = 0

        def download_artifact(self, _artifact_id: str) -> bytes:
            self.downloads += 1
            return source.getvalue()

        def upload_artifact(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            self.uploads += 1
            return {"id": "artifact_output"}

    client = Client()
    example.client = client
    offer = {
        "type": "task.offer",
        "agent_id": "agent_media",
        "run_id": "run_replayed",
        "payload": {"task_id": "task_media", "input_artifact_ids": ["artifact_input"]},
    }
    first = await example.handle(offer)
    second = await example.handle(offer)

    assert client.downloads == 1 and client.uploads == 1
    assert [item.as_dict() for item in second] == [item.as_dict() for item in first]


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def media_contract_app(
    input_png: bytes,
    output: dict[str, Any],
    result_received: threading.Event,
) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/agent-auth/token")
    async def authenticate(request: Request) -> dict[str, str]:
        body = await request.json()
        output["credential"] = body["credential"]
        return {"access_token": "media-agent-token", "agent_id": "agent_media"}

    @app.get("/v1/agent-callbacks/artifacts/artifact_input/download")
    def download_grant(request: Request) -> dict[str, str]:
        assert request.headers["authorization"] == "Bearer media-agent-token"
        return {"url": str(request.base_url) + "objects/input"}

    @app.get("/objects/input")
    def input_object() -> Response:
        return Response(input_png, media_type="image/png")

    @app.post("/v1/agent-callbacks/artifacts/uploads", status_code=201)
    async def begin_upload(request: Request) -> dict[str, object]:
        assert request.headers["authorization"] == "Bearer media-agent-token"
        body = await request.json()
        output["declaration"] = body
        return {"id": "artifact_output"}

    @app.post("/v1/agent-callbacks/artifacts/artifact_output/parts/1")
    def sign_part(request: Request) -> dict[str, str]:
        assert request.headers["authorization"] == "Bearer media-agent-token"
        return {"url": str(request.base_url) + "objects/output"}

    @app.put("/objects/output")
    async def output_object(request: Request) -> Response:
        payload = await request.body()
        output["bytes"] = payload
        return Response(status_code=200, headers={"etag": '"media-etag"'})

    @app.post("/v1/agent-callbacks/artifacts/artifact_output/complete")
    async def complete_upload(request: Request) -> dict[str, object]:
        assert request.headers["authorization"] == "Bearer media-agent-token"
        output["completion"] = await request.json()
        return {
            "id": "artifact_output",
            "kind": "image",
            "mime_type": "image/png",
            "size_bytes": len(output["bytes"]),
            "sha256": hashlib.sha256(output["bytes"]).hexdigest(),
            "scan_status": "clean",
            "metadata": {"width": 64, "height": 64},
        }

    @app.websocket("/v1/agents/connect")
    async def connect(websocket: WebSocket) -> None:
        assert websocket.headers["authorization"] == "Bearer media-agent-token"
        assert "workworld.v1" in websocket.headers["sec-websocket-protocol"]
        await websocket.accept(subprotocol="workworld.v1")
        await websocket.send_json(
            {
                "protocol_version": "1.0",
                "message_id": "00000000-0000-4000-8000-000000000201",
                "idempotency_key": "agent.registered:media",
                "timestamp": "2026-08-11T00:00:00Z",
                "agent_id": "agent_media",
                "run_id": "run_system",
                "type": "agent.registered",
                "sequence": 1,
                "payload": {"generation": 1},
            }
        )
        await websocket.send_json(
            {
                "protocol_version": "1.0",
                "message_id": "00000000-0000-4000-8000-000000000202",
                "idempotency_key": "run_media:task.offer:1",
                "timestamp": "2026-08-11T00:00:00Z",
                "agent_id": "agent_media",
                "run_id": "run_media",
                "type": "task.offer",
                "sequence": 1,
                "payload": {
                    "task_id": "task_media",
                    "input_artifact_ids": ["artifact_input"],
                },
            }
        )
        output["messages"] = []
        while True:
            document = json.loads(await websocket.receive_text())
            output["messages"].append(document)
            if document["type"] == "task.result_submitted":
                result_received.set()
                return

    return app


def test_media_echo_example_runs_as_process_and_transforms_real_png(tmp_path: Path) -> None:
    source = io.BytesIO()
    Image.new("RGB", (64, 64), color="blue").save(source, format="PNG")
    input_png = source.getvalue()
    output: dict[str, Any] = {}
    result_received = threading.Event()
    port = unused_port()
    server = uvicorn.Server(
        uvicorn.Config(
            media_contract_app(input_png, output, result_received),
            host="127.0.0.1",
            port=port,
            log_level="critical",
            lifespan="off",
            timeout_keep_alive=1,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    root = Path(__file__).parents[3]
    environment = os.environ.copy()
    environment.update(
        {
            "WORKWORLD_API_URL": f"http://127.0.0.1:{port}",
            "WORKWORLD_AGENT_CREDENTIAL": "wwa_media.process-credential",
            "PYTHONPATH": str(root / "sdk" / "python" / "src"),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(root / "examples" / "python-media-echo-agent" / "agent.py")],
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert result_received.wait(15), "media example did not submit a result"
        assert process.poll() is None
        assert output["credential"] == "wwa_media.process-credential"
        declaration = output["declaration"]
        payload = output["bytes"]
        assert declaration["task_id"] == "task_media"
        assert declaration["kind"] == "image"
        assert declaration["mime_type"] == "image/png"
        assert declaration["size_bytes"] == len(payload)
        assert declaration["sha256"] == hashlib.sha256(payload).hexdigest()
        assert output["completion"] == {"parts": [{"PartNumber": 1, "ETag": "media-etag"}]}
        messages = output["messages"]
        assert [message["type"] for message in messages] == [
            "agent.capacity_updated",
            "task.accept",
            "task.started",
            "task.result_submitted",
        ]
        assert messages[-1]["payload"]["output"] == {"artifact_id": "artifact_output"}
        with Image.open(io.BytesIO(payload)) as image:
            assert image.size == (64, 64)
            assert image.convert("RGB").getpixel((8, 8)) == (255, 0, 0)
            assert image.convert("RGB").getpixel((40, 40)) == (0, 0, 255)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.returncode not in {0, -15}:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"media example exited with {process.returncode}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        server.should_exit = True
        thread.join(timeout=10)
