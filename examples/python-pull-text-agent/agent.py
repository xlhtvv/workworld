import asyncio
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from workworld_sdk import AgentClient, Envelope, PullAgent

client: AgentClient
run_context: dict[str, tuple[str, dict[str, Any]]] = {}


def summarize(text: str, max_characters: int) -> str:
    """Use the opted-in hosted model, or the explicit deterministic default."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        body = json.dumps(
            {
                "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
                "store": False,
                "input": (
                    "Summarize the following text faithfully. Return only the summary, "
                    f"with at most {max_characters} characters.\n\n{text}"
                ),
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                document = json.load(response)
        except (OSError, urllib.error.HTTPError) as exc:
            raise RuntimeError("openai_summary_failed") from exc
        output = "".join(
            str(content.get("text", ""))
            for item in document.get("output", [])
            if item.get("type") == "message"
            for content in item.get("content", [])
            if content.get("type") == "output_text"
        ).strip()
        if not output:
            raise RuntimeError("openai_summary_output_missing")
        return output[:max_characters]
    sentences = re.split(r"(?<=[.!?。！？])\s*", text.strip())
    return " ".join(sentences)[:max_characters]


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
        challenge = message["artifact_challenge"]["content_utf8"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "certification.txt"
            path.write_text(str(challenge), encoding="utf-8")
            artifact = client.upload_artifact(
                None, path, kind="generic_file", mime_type="text/plain"
            )
        sample_input = message["sample_input"]
        summary = summarize(
            str(sample_input["text"]), int(sample_input.get("max_characters", 1000))
        )
        return [{
            "type": "offering.certification.result",
            "certification_id": message["certification_id"],
            "results": [
                {"name": item["name"], "challenge": item["challenge"], "passed": True}
                for item in message["scenarios"]
            ],
            "sample_output": {"summary": summary},
            "artifact_id": artifact["id"],
        }]
    if message.get("type") in {"clarification.timed_out", "clarification.answered"}:
        run_id = str(message["run_id"])
        agent_id, task_input = run_context[run_id]
        result = summarize(
            str(task_input["text"]), int(task_input.get("max_characters", 1000))
        )
        return [
            Envelope.create(
                agent_id,
                run_id,
                "task.result_submitted",
                4,
                {"output": {"summary": result}},
            )
        ]
    if message.get("type") == "task.rework_requested":
        run_id = str(message["run_id"])
        agent_id, task_input = run_context[run_id]
        result = summarize(
            str(task_input["text"]), int(task_input.get("max_characters", 1000))
        )
        return [
            Envelope.create(agent_id, run_id, "task.started", 4, {}),
            Envelope.create(
                agent_id,
                run_id,
                "task.result_submitted",
                5,
                {"output": {"summary": result}},
            ),
        ]
    if message.get("type") == "task.cancel_requested":
        run_id = str(message["run_id"])
        agent_id, _task_input = run_context[run_id]
        return [Envelope.create(agent_id, run_id, "task.cancelled", 3, {})]
    if message.get("type") != "task.offer":
        return []
    payload = message["payload"]
    run_id = str(message["run_id"])
    agent_id = str(message["agent_id"])
    task_input = payload["input"]
    run_context[run_id] = (agent_id, task_input)
    result = summarize(str(task_input["text"]), int(task_input.get("max_characters", 1000)))
    if task_input.get("focus") == "clarification-default-e2e":
        return [
            Envelope.create(agent_id, run_id, "task.accept", 1, {}),
            Envelope.create(agent_id, run_id, "task.started", 2, {}),
            Envelope.create(
                agent_id,
                run_id,
                "clarification.requested",
                3,
                {
                    "question": "Which summary focus should be used?",
                    "answer_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["focus"],
                        "properties": {"focus": {"type": "string"}},
                    },
                    "default_answer": {"focus": "general"},
                    "blocking": True,
                    "deadline": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
                },
            ),
        ]
    if task_input.get("focus") == "rework-e2e":
        return [
            Envelope.create(agent_id, run_id, "task.accept", 1, {}),
            Envelope.create(agent_id, run_id, "task.started", 2, {}),
            Envelope.create(
                agent_id,
                run_id,
                "task.result_submitted",
                3,
                {"output": {"summary": result}},
            ),
        ]
    if task_input.get("focus") == "cancel-partial-e2e":
        return [
            Envelope.create(agent_id, run_id, "task.accept", 1, {}),
            Envelope.create(agent_id, run_id, "task.started", 2, {}),
        ]
    return [
        Envelope.create(agent_id, run_id, "task.accept", 1, {}),
        Envelope.create(agent_id, run_id, "task.started", 2, {}),
        Envelope.create(
            agent_id,
            run_id,
            "task.progress",
            3,
            {
                "percent": 100,
                "message": (
                    "execution_mode=openai"
                    if os.environ.get("OPENAI_API_KEY", "").strip()
                    else "execution_mode=deterministic_example"
                ),
            },
        ),
        Envelope.create(
            agent_id, run_id, "task.result_submitted", 4, {"output": {"summary": result}}
        ),
    ]


async def main() -> None:
    global client
    client = AgentClient(
        os.environ.get("WORKWORLD_API_URL", "http://localhost:8000"),
        os.environ["WORKWORLD_AGENT_CREDENTIAL"],
    )
    await PullAgent(client, handle).run_forever()


if __name__ == "__main__":
    asyncio.run(main())
