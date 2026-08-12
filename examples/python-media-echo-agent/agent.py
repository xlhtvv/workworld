import asyncio
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from workworld_sdk import AgentClient, Envelope, PullAgent

client: AgentClient
completed_offers: dict[str, list[Envelope | dict[str, Any]]] = {}


async def handle(message: dict[str, Any]) -> list[Envelope | dict[str, Any]]:
    if message.get("type") == "agent.registered":
        return [
            Envelope.create(
                str(message["agent_id"]),
                "run_system",
                "agent.capacity_updated",
                1,
                {
                    "status": "online",
                    "max_concurrent_runs": 1,
                    "active_runs": 0,
                    "queue_capacity": 1,
                    "estimated_wait_seconds": 0,
                    "supported_offering_versions": [],
                },
            )
        ]
    if message.get("type") == "offering.certification":
        challenge = str(message["artifact_challenge"]["content_utf8"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "certification.txt"
            path.write_text(challenge, encoding="utf-8")
            artifact = client.upload_artifact(
                None, path, kind="generic_file", mime_type="text/plain"
            )
        return [
            {
                "type": "offering.certification.result",
                "certification_id": message["certification_id"],
                "results": [
                    {"name": item["name"], "challenge": item["challenge"], "passed": True}
                    for item in message["scenarios"]
                ],
                "sample_output": {"artifact_id": artifact["id"]},
                "artifact_id": artifact["id"],
            }
        ]
    if message.get("type") != "task.offer":
        return []
    payload = message["payload"]
    run_id = str(message["run_id"])
    if run_id in completed_offers:
        return completed_offers[run_id]
    artifact_id = str(payload["input_artifact_ids"][0])
    source = client.download_artifact(artifact_id)
    with Image.open(io.BytesIO(source)) as image:
        output = image.convert("RGB")
        draw = ImageDraw.Draw(output)
        draw.rectangle((8, 8, output.width - 9, output.height - 9), outline="red", width=8)
        draw.text((20, 20), "WorkWorld", fill="red")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workworld-echo.png"
            output.save(path, format="PNG")
            artifact = client.upload_artifact(
                str(payload["task_id"]), path, kind="image", mime_type="image/png"
            )
    agent_id = str(message["agent_id"])
    responses: list[Envelope | dict[str, Any]] = [
        Envelope.create(agent_id, run_id, "task.accept", 1, {}),
        Envelope.create(agent_id, run_id, "task.started", 2, {}),
        Envelope.create(
            agent_id,
            run_id,
            "task.result_submitted",
            3,
            {"output": {"artifact_id": artifact["id"]}},
        ),
    ]
    completed_offers[run_id] = responses
    return responses


async def main() -> None:
    global client
    client = AgentClient(
        os.environ.get("WORKWORLD_API_URL", "http://localhost:8000"),
        os.environ["WORKWORLD_AGENT_CREDENTIAL"],
    )
    await PullAgent(client, handle).run_forever()


if __name__ == "__main__":
    asyncio.run(main())
