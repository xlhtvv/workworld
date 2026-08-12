import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import websockets
from sqlalchemy import select
from websockets.typing import Subprotocol
from workworld_api.config import get_settings
from workworld_api.database import Base, session_factory
from workworld_api.main import create_app
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentConnection,
    Offering,
    OfferingVersion,
)
from workworld_api.task_models import ProtocolOutbox, Run, RunEvent, Task
from workworld_sdk import AgentClient, Envelope


def load_pull_example() -> Any:
    root = Path(__file__).parents[3]
    path = root / "examples" / "python-pull-text-agent" / "agent.py"
    spec = importlib.util.spec_from_file_location("workworld_pull_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request_json(
    method: str,
    url: str,
    document: object | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(document).encode() if document is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return dict(json.load(response))


def wait_until_ready(base_url: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            request_json("GET", f"{base_url}/health")
            return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("live API did not become ready")


def wait_for_run_and_acknowledgement(
    run_id: str, outbox_id: str, state: str, process: subprocess.Popen[str]
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"example Agent exited with {process.returncode}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        with session_factory()() as db:
            run = db.get(Run, run_id)
            outbox = db.get(ProtocolOutbox, outbox_id)
            if (
                run is not None
                and run.state == state
                and outbox is not None
                and outbox.status == "acknowledged"
            ):
                return
        time.sleep(0.05)
    raise AssertionError(f"example Agent did not reach {state} with acknowledged offer")


def seed_offer(agent_id: str, publisher_id: str) -> tuple[str, str]:
    now = datetime.now(UTC)
    run_id = "run_livepull"
    event_id = "event_live_pull_offer"
    with session_factory()() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        offering = Offering(
            id="offering_live_pull",
            agent_id=agent.id,
            owner_id=agent.owner_id,
            slug="live-pull",
            status="published",
            latest_version_id="offering_live_pull_v1",
            created_at=now,
        )
        version = OfferingVersion(
            id="offering_live_pull_v1",
            offering_id=offering.id,
            version=1,
            schema_id="text.summarize",
            schema_version="1.0",
            name_i18n={"en": "Live Pull", "zh": "真实 Pull"},
            description_i18n={"en": "Transport test", "zh": "传输测试"},
            capabilities=[],
            risk_disclosure="Local integration test.",
            output_license="publisher-use",
            sla_seconds=60,
            input_limits={"max_characters": 1000},
            estimated_tokens_min=1,
            estimated_tokens_max=100,
            estimated_seconds_min=1,
            estimated_seconds_max=60,
            auto_apply_policy={"enabled": False},
            status="published",
            content_sha256="1" * 64,
            created_at=now,
            published_at=now,
        )
        task = Task(
            id="task_live_pull",
            publisher_id=publisher_id,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Live Pull transport",
            public_summary="Exercise durable WebSocket delivery.",
            input_json={"text": "source", "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={"max_characters": 1000},
            budget_tokens=100,
            completion_deadline=now + timedelta(hours=1),
            assignment_mode="recommended",
            status="candidate_selected",
            created_at=now,
        )
        run = Run(
            id=run_id,
            task_id=task.id,
            attempt=1,
            offering_version_id=version.id,
            agent_id=agent.id,
            state="offer_sent",
            protocol_version="1.0",
            schema_version_id="text.summarize@1.0",
            last_agent_sequence=0,
            next_event_sequence=2,
            clarification_rounds=0,
            rework_count=0,
            offer_expires_at=now + timedelta(minutes=10),
            completion_deadline=task.completion_deadline,
            created_at=now,
        )
        event = RunEvent(
            id=event_id,
            run_id=run.id,
            sequence=1,
            agent_sequence=None,
            message_id="00000000-0000-4000-8000-000000000101",
            idempotency_key="offer:live-pull",
            event_type="task.offer",
            actor_type="system",
            actor_id=None,
            payload_json={"task_id": task.id, "input": task.input_json},
            created_at=now,
        )
        outbox = ProtocolOutbox(
            id="outbox_live_pull",
            run_event_id=event.id,
            agent_id=agent.id,
            status="pending",
            attempts=0,
            available_at=now,
        )
        db.add_all([offering, version, task, run, event, outbox])
        db.commit()
    return run_id, event_id


@pytest.mark.asyncio
async def test_live_pull_disconnect_reconnect_replays_and_acknowledges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "live-pull.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("WORKWORLD_ENV", "test")
    get_settings.cache_clear()
    session_factory.cache_clear()
    factory = session_factory()
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
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
    try:
        await asyncio.to_thread(wait_until_ready, base_url)
        provider = await asyncio.to_thread(
            request_json,
            "POST",
            f"{base_url}/v1/auth/register",
            {"email": "live-provider@example.com", "password": "correct horse battery staple"},
        )
        publisher = await asyncio.to_thread(
            request_json,
            "POST",
            f"{base_url}/v1/auth/register",
            {"email": "live-publisher@example.com", "password": "correct horse battery staple"},
        )
        client = await asyncio.to_thread(
            AgentClient.provision,
            base_url,
            str(provider["access_token"]),
            name="Live Pull Agent",
            endpoint_type="pull",
        )
        credential_token = await asyncio.to_thread(client.authenticate)
        assert client.agent_id is not None
        run_id, event_id = seed_offer(client.agent_id, str(publisher["user_id"]))
        socket_url = f"ws://127.0.0.1:{port}/v1/agents/connect"
        headers = {"Authorization": f"Bearer {credential_token}"}

        async with websockets.connect(
            socket_url,
            additional_headers=headers,
            subprotocols=[Subprotocol("workworld.v1")],
        ) as first:
            registered = json.loads(await first.recv())
            first_offer = json.loads(await first.recv())
            assert registered["type"] == "agent.registered"
            assert first_offer["type"] == "task.offer"
            assert first_offer["message_id"] == "00000000-0000-4000-8000-000000000101"

        async with websockets.connect(
            socket_url,
            additional_headers=headers,
            subprotocols=[Subprotocol("workworld.v1")],
        ) as second:
            registered_again = json.loads(await second.recv())
            replayed = json.loads(await second.recv())
            assert registered_again["payload"]["generation"] == 2
            assert replayed["message_id"] == first_offer["message_id"]
            accepted = Envelope.create(client.agent_id, run_id, "task.accept", 1, {})
            await second.send(json.dumps(accepted.as_dict()))
            started = Envelope.create(client.agent_id, run_id, "task.started", 2, {})
            await second.send(json.dumps(started.as_dict()))
            result = Envelope.create(
                client.agent_id,
                run_id,
                "task.result_submitted",
                3,
                {"output": {"summary": "Delivered through a real Pull WebSocket."}},
            )
            await second.send(json.dumps(result.as_dict()))
            heartbeat = Envelope.create(
                client.agent_id,
                "run_system",
                "agent.heartbeat",
                1,
                {
                    "acknowledged_sequence": 3,
                    "acknowledged_event_ids": [event_id],
                    "acknowledged_message_ids": [replayed["message_id"]],
                },
            )
            await second.send(json.dumps(heartbeat.as_dict()))
            await asyncio.sleep(0.2)

        with session_factory()() as db:
            connections = list(
                db.scalars(
                    select(AgentConnection)
                    .where(AgentConnection.agent_id == client.agent_id)
                    .order_by(AgentConnection.generation)
                )
            )
            run = db.get(Run, run_id)
            outbox = db.get(ProtocolOutbox, "outbox_live_pull")
            assert [row.generation for row in connections] == [1, 2]
            assert connections[0].disconnected_at is not None
            assert run is not None and run.state == "result_submitted"
            assert run.last_agent_sequence == 3
            assert outbox is not None and outbox.status == "acknowledged"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        session_factory.cache_clear()
        get_settings.cache_clear()


def test_python_pull_text_example_runs_as_process_and_submits_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pull-example.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("WORKWORLD_ENV", "test")
    get_settings.cache_clear()
    session_factory.cache_clear()
    factory = session_factory()
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
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
    process: subprocess.Popen[str] | None = None
    try:
        wait_until_ready(base_url)
        provider = request_json(
            "POST",
            f"{base_url}/v1/auth/register",
            {"email": "example-provider@example.com", "password": "correct horse battery staple"},
        )
        publisher = request_json(
            "POST",
            f"{base_url}/v1/auth/register",
            {"email": "example-publisher@example.com", "password": "correct horse battery staple"},
        )
        client = AgentClient.provision(
            base_url,
            str(provider["access_token"]),
            name="Process Pull Text Agent",
            endpoint_type="pull",
        )
        assert client.agent_id is not None
        run_id, _event_id = seed_offer(client.agent_id, str(publisher["user_id"]))
        root = Path(__file__).parents[3]
        environment = os.environ.copy()
        environment.update(
            {
                "WORKWORLD_API_URL": base_url,
                "WORKWORLD_AGENT_CREDENTIAL": client.credential,
                "PYTHONPATH": str(root / "sdk" / "python" / "src"),
            }
        )
        process = subprocess.Popen(
            [sys.executable, str(root / "examples" / "python-pull-text-agent" / "agent.py")],
            cwd=root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_for_run_and_acknowledgement(
            run_id, "outbox_live_pull", "result_submitted", process
        )
        with session_factory()() as db:
            run = db.get(Run, run_id)
            capacity = db.scalar(
                select(AgentCapacitySnapshot)
                .where(AgentCapacitySnapshot.agent_id == client.agent_id)
                .order_by(AgentCapacitySnapshot.observed_at.desc())
            )
            events = list(
                db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id)
                    .order_by(RunEvent.sequence)
                )
            )
            outbox = db.get(ProtocolOutbox, "outbox_live_pull")
            assert run is not None and run.last_agent_sequence == 4
            assert [event.event_type for event in events] == [
                "task.offer",
                "task.accept",
                "task.started",
                "task.progress",
                "task.result_submitted",
            ]
            assert events[-2].payload_json["message"] == "execution_mode=deterministic_example"
            assert events[-1].payload_json["output"] == {"summary": "source"}
            assert outbox is not None and outbox.status == "acknowledged"
            assert capacity is not None
            assert capacity.status == "online"
            assert capacity.max_concurrent_runs == 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        session_factory.cache_clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pull_example_continues_after_defaulted_clarification_and_one_rework() -> None:
    example = load_pull_example()
    base_offer = {
        "type": "task.offer",
        "agent_id": "agent_example",
        "run_id": "run_controls",
        "payload": {
            "task_id": "task_controls",
            "input": {
                "text": "Control-path source.",
                "max_characters": 1000,
                "difficulty": "simple",
                "focus": "clarification-default-e2e",
            },
        },
    }

    clarification = await example.handle(base_offer)
    assert [response.type for response in clarification] == [
        "task.accept",
        "task.started",
        "clarification.requested",
    ]
    resumed = await example.handle(
        {"type": "clarification.timed_out", "run_id": "run_controls"}
    )
    assert [response.type for response in resumed] == ["task.result_submitted"]
    assert resumed[0].sequence == 4

    rework_offer = {
        **base_offer,
        "run_id": "run_rework",
        "payload": {
            **base_offer["payload"],
            "input": {**base_offer["payload"]["input"], "focus": "rework-e2e"},
        },
    }
    first_round = await example.handle(rework_offer)
    assert [response.type for response in first_round] == [
        "task.accept",
        "task.started",
        "task.result_submitted",
    ]
    second_round = await example.handle(
        {"type": "task.rework_requested", "run_id": "run_rework"}
    )
    assert [(response.type, response.sequence) for response in second_round] == [
        ("task.started", 4),
        ("task.result_submitted", 5),
    ]


@pytest.mark.asyncio
async def test_pull_example_acknowledges_cancellation_after_start() -> None:
    example = load_pull_example()
    offer = {
        "type": "task.offer",
        "agent_id": "agent_cancel",
        "run_id": "run_cancel",
        "payload": {
            "task_id": "task_cancel",
            "input": {
                "text": "Create one verified stage before cancellation.",
                "max_characters": 1000,
                "difficulty": "simple",
                "focus": "cancel-partial-e2e",
            },
        },
    }

    started = await example.handle(offer)
    assert [(response.type, response.sequence) for response in started] == [
        ("task.accept", 1),
        ("task.started", 2),
    ]
    cancelled = await example.handle(
        {"type": "task.cancel_requested", "run_id": "run_cancel"}
    )
    assert [(response.type, response.sequence) for response in cancelled] == [
        ("task.cancelled", 3)
    ]
