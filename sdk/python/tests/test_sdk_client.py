import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from workworld_sdk import AgentClient


class ProvisionHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, Any], str]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        document = json.loads(self.rfile.read(length))
        self.requests.append((self.path, document, self.headers.get("authorization", "")))
        if self.path == "/v1/agents":
            result = {"id": "agent_1"}
        elif self.path.endswith("/credentials"):
            result = {"credential": "wwa_000000000000.secret"}
        elif self.path == "/v1/agent-auth/token":
            result = {"access_token": "agent-token", "agent_id": "agent_1"}
        elif self.path == "/v1/agent-callbacks/capacity":
            self.send_response(204)
            self.end_headers()
            return
        else:
            result = {"id": "endpoint_1", "status": "pending"}
        payload = json.dumps(result).encode()
        self.send_response(201)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_provision_uses_real_http_and_returns_credentialed_client() -> None:
    ProvisionHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProvisionHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        client = AgentClient.provision(
            f"http://127.0.0.1:{server.server_port}",
            "human-token",
            name="Pull Agent",
            endpoint_type="pull",
        )
        client.update_capacity(
            status="online",
            max_concurrent_runs=1,
            active_runs=0,
            queue_capacity=1,
            estimated_wait_seconds=0,
            supported_offering_versions=[],
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert client.agent_id == "agent_1"
    assert [path for path, _body, _auth in ProvisionHandler.requests] == [
        "/v1/agents",
        "/v1/agents/agent_1/credentials",
        "/v1/agents/agent_1/endpoints",
        "/v1/agent-auth/token",
        "/v1/agent-callbacks/capacity",
    ]
    assert all(
        auth == "Bearer human-token"
        for _path, _body, auth in ProvisionHandler.requests[:3]
    )
    assert ProvisionHandler.requests[-1][2] == "Bearer agent-token"
    assert ProvisionHandler.requests[2][1] == {"endpoint_type": "pull", "url": None}
    assert ProvisionHandler.requests[-1][1]["status"] == "online"
