import json
import socket
import ssl
import subprocess
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from sqlalchemy import select
from workworld_api.config import Settings, get_settings
from workworld_api.database import Base, session_factory
from workworld_api.main import create_app
from workworld_api.market_models import Agent, AgentEndpoint, Offering, OfferingVersion
from workworld_api.services.endpoint_security import (
    PinnedHTTPSVerifier,
    ValidatedEndpoint,
    verify_webhook,
)
from workworld_api.services.push_delivery import PushDeliveryService
from workworld_api.task_models import ProtocolOutbox, Run, RunEvent, Task
from workworld_sdk import AgentClient, Envelope


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request_json(method: str, url: str, document: object) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(document).encode(),
        headers={"content-type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return dict(json.load(response))


def wait_until_ready(base_url: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("live API did not become ready")


def create_certificate(directory: Path) -> tuple[Path, Path]:
    certificate = directory / "localhost.crt"
    private_key = directory / "localhost.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return certificate, private_key


class PushProviderHandler(BaseHTTPRequestHandler):
    client: AgentClient
    secret: str
    nonces: set[str] = set()
    received_types: list[str] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        signature = self.headers.get("x-workworld-signature")
        if signature is None:
            challenge = json.loads(body)["challenge"]
            self._reply(200, {"challenge": challenge})
            return
        timestamp = int(self.headers["x-workworld-timestamp"])
        nonce = self.headers["x-workworld-nonce"]
        verify_webhook(self.secret, timestamp, nonce, body, signature)
        if nonce in self.nonces:
            self._reply(409, {"error": "nonce_replayed"})
            return
        self.nonces.add(nonce)
        envelope = json.loads(body)
        self.received_types.append(str(envelope["type"]))
        agent_id = str(envelope["agent_id"])
        run_id = str(envelope["run_id"])
        self.client.callback(Envelope.create(agent_id, run_id, "task.accept", 1, {}))
        self.client.callback(Envelope.create(agent_id, run_id, "task.started", 2, {}))
        self.client.callback(
            Envelope.create(
                agent_id,
                run_id,
                "task.result_submitted",
                3,
                {"output": {"summary": "Delivered through real signed HTTPS Push."}},
            )
        )
        self._reply(202, {"accepted": True})

    def _reply(self, status: int, document: object) -> None:
        payload = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def seed_push_offer(agent_id: str, publisher_id: str, endpoint_url: str) -> str:
    now = datetime.now(UTC)
    run_id = "run_livepush"
    with session_factory()() as db:
        endpoint = db.scalar(select(AgentEndpoint).where(AgentEndpoint.agent_id == agent_id))
        assert endpoint is not None
        agent = db.get(Agent, agent_id)
        assert agent is not None
        endpoint.endpoint_type = "push"
        endpoint.url = endpoint_url
        endpoint.status = "verified"
        endpoint.resolved_addresses = ["127.0.0.1"]
        endpoint.verified_at = now
        offering = Offering(
            id="offering_live_push",
            agent_id=agent_id,
            owner_id=agent.owner_id,
            slug="live-push",
            status="published",
            latest_version_id="offering_live_push_v1",
            created_at=now,
        )
        version = OfferingVersion(
            id="offering_live_push_v1",
            offering_id=offering.id,
            version=1,
            schema_id="text.summarize",
            schema_version="1.0",
            name_i18n={"en": "Live Push", "zh": "真实 Push"},
            description_i18n={"en": "TLS transport", "zh": "TLS 传输"},
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
            content_sha256="2" * 64,
            created_at=now,
            published_at=now,
        )
        task = Task(
            id="task_live_push",
            publisher_id=publisher_id,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Live Push transport",
            public_summary="Exercise signed HTTPS delivery and callbacks.",
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
            agent_id=agent_id,
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
            id="event_live_push_offer",
            run_id=run.id,
            sequence=1,
            agent_sequence=None,
            message_id="00000000-0000-4000-8000-000000000202",
            idempotency_key="offer:live-push",
            event_type="task.offer",
            actor_type="system",
            actor_id=None,
            payload_json={"task_id": task.id, "input": task.input_json},
            created_at=now,
        )
        db.add_all(
            [
                offering,
                version,
                task,
                run,
                event,
                ProtocolOutbox(
                    id="outbox_live_push",
                    run_event_id=event.id,
                    agent_id=agent_id,
                    status="pending",
                    attempts=0,
                    available_at=now,
                ),
            ]
        )
        db.commit()
    return run_id


def test_live_push_tls_signature_callbacks_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'live-push.db'}")
    monkeypatch.setenv("WORKWORLD_ENV", "test")
    get_settings.cache_clear()
    session_factory.cache_clear()
    factory = session_factory()
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    api_port = unused_port()
    api_url = f"http://127.0.0.1:{api_port}"
    api_server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host="127.0.0.1",
            port=api_port,
            log_level="critical",
            lifespan="off",
            timeout_keep_alive=1,
            timeout_graceful_shutdown=1,
        )
    )
    api_thread = threading.Thread(target=api_server.run, daemon=True)
    api_thread.start()
    provider_server: ThreadingHTTPServer | None = None
    provider_thread: threading.Thread | None = None
    try:
        wait_until_ready(api_url)
        provider = request_json(
            "POST",
            f"{api_url}/v1/auth/register",
            {"email": "push-provider@example.com", "password": "correct horse battery staple"},
        )
        publisher = request_json(
            "POST",
            f"{api_url}/v1/auth/register",
            {"email": "push-publisher@example.com", "password": "correct horse battery staple"},
        )
        client = AgentClient.provision(
            api_url,
            str(provider["access_token"]),
            name="Live Push Agent",
            endpoint_type="pull",
        )
        client.authenticate()
        assert client.agent_id is not None
        certificate, private_key = create_certificate(tmp_path)
        PushProviderHandler.client = client
        settings = Settings()
        PushProviderHandler.secret = settings.push_signing_secret
        PushProviderHandler.nonces = set()
        PushProviderHandler.received_types = []
        provider_server = ThreadingHTTPServer(("127.0.0.1", 0), PushProviderHandler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(certificate, private_key)
        provider_server.socket = tls.wrap_socket(provider_server.socket, server_side=True)
        provider_thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
        provider_thread.start()
        endpoint_url = f"https://localhost:{provider_server.server_port}/workworld"
        validated = ValidatedEndpoint(
            endpoint_url,
            "localhost",
            provider_server.server_port,
            frozenset({"127.0.0.1"}),
        )
        verifier = PinnedHTTPSVerifier(ca_file=str(certificate))
        verifier.verify_challenge(validated, "real-tls-challenge")
        run_id = seed_push_offer(client.agent_id, str(publisher["user_id"]), endpoint_url)
        with session_factory()() as db:
            service = PushDeliveryService(
                db,
                settings,
                sender=verifier.post_signed_json,
                endpoint_validator=lambda _url: validated,
            )
            assert service.dispatch_due() == (1, 0)
        with session_factory()() as db:
            run = db.get(Run, run_id)
            outbox = db.get(ProtocolOutbox, "outbox_live_push")
            assert run is not None and run.state == "result_submitted"
            assert run.last_agent_sequence == 3
            assert outbox is not None and outbox.status == "acknowledged"
        assert PushProviderHandler.received_types == ["task.offer"]
        assert len(PushProviderHandler.nonces) == 1
    finally:
        if provider_server is not None:
            provider_server.shutdown()
            provider_server.server_close()
        if provider_thread is not None:
            provider_thread.join(timeout=5)
        api_server.should_exit = True
        api_thread.join(timeout=10)
        engine.dispose()
        session_factory.cache_clear()
        get_settings.cache_clear()
