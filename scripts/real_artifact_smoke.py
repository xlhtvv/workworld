"""Real-service smoke: API + PostgreSQL + MinIO + ClamAV, with no test doubles."""

import hashlib
import json
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

API = "http://localhost:8000"


def decode_response(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode(errors="replace")


def request(
    method: str,
    path: str,
    document: object | None = None,
    token: str | None = None,
) -> tuple[int, Any, dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(document).encode() if document is not None else None
    operation = urllib.request.Request(f"{API}{path}", body, headers, method=method)
    try:
        with urllib.request.urlopen(operation, timeout=180) as response:
            payload = response.read()
            return response.status, decode_response(payload), dict(response.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        return exc.code, decode_response(payload), dict(exc.headers)


def register(label: str) -> str:
    status, document, _headers = request(
        "POST",
        "/v1/auth/register",
        {
            "email": f"smoke-{label}-{uuid.uuid4().hex}@example.com",
            "password": "smoke-password-123",
        },
    )
    assert status == 201, document
    return str(document["access_token"])


def main() -> None:
    owner_token = register("owner")
    stranger_token = register("stranger")
    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(
            executor.map(
                lambda _index: request(
                    "POST", "/v1/wallet/daily-grant", token=owner_token
                ),
                range(12),
            )
        )
    assert all(status == 200 for status, _document, _headers in claims), claims
    status, wallet, _headers = request("GET", "/v1/wallet", token=owner_token)
    assert status == 200, wallet
    assert wallet["balances"]["user_available"] == 110_000, wallet
    payload = b"WorkWorld real ClamAV and MinIO smoke artifact.\n"
    sha256 = hashlib.sha256(payload).hexdigest()
    status, artifact, _headers = request(
        "POST",
        "/v1/artifacts/uploads",
        {
            "original_name": "smoke.txt",
            "kind": "text",
            "direction": "input",
            "mime_type": "text/plain",
            "size_bytes": len(payload),
            "sha256": sha256,
            "task_id": None,
        },
        owner_token,
    )
    assert status == 201, artifact
    artifact_id = str(artifact["id"])
    status, signed, _headers = request(
        "POST", f"/v1/artifacts/{artifact_id}/parts/1", token=owner_token
    )
    assert status == 200, signed
    upload = urllib.request.Request(str(signed["url"]), payload, method="PUT")
    try:
        with urllib.request.urlopen(upload, timeout=120) as response:
            assert response.status == 200
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise AssertionError(
            f"artifact part upload failed status={exc.code} body={error_body}"
        ) from exc
    status, completed, _headers = request(
        "POST",
        f"/v1/artifacts/{artifact_id}/complete",
        {"parts": []},
        owner_token,
    )
    assert status == 200, completed
    assert completed["scan_status"] == "clean", completed
    assert completed["sha256"] == sha256, completed
    assert completed["metadata"]["character_count"] == len(payload.decode()), completed
    status, denied, _headers = request(
        "GET", f"/v1/artifacts/{artifact_id}/download", token=stranger_token
    )
    assert status == 404, denied
    status, granted, _headers = request(
        "GET", f"/v1/artifacts/{artifact_id}/download", token=owner_token
    )
    assert status == 200 and granted["url"].startswith("http://localhost:9000"), granted
    print(f"real artifact smoke passed artifact_id={artifact_id}")


if __name__ == "__main__":
    main()
