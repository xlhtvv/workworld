#!/usr/bin/env python3
"""Exercise image.edit with a real Pull Agent, MinIO, ClamAV, and metering."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

from PIL import Image
from real_pull_journey import (
    API_URL,
    ROOT,
    JourneyError,
    register,
    request_json,
    stop_process,
    wait_for,
)


def upload_input(token: str, task_id: str, payload: bytes) -> dict[str, object]:
    artifact = request_json(
        "POST",
        "/v1/artifacts/uploads",
        {
            "original_name": "source.png",
            "kind": "image",
            "direction": "input",
            "mime_type": "image/png",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "task_id": task_id,
        },
        token,
    )
    artifact_id = str(artifact["id"])
    signed = request_json("POST", f"/v1/artifacts/{artifact_id}/parts/1", token=token)
    upload = urllib.request.Request(str(signed["url"]), data=payload, method="PUT")
    with urllib.request.urlopen(upload, timeout=120) as response:
        if response.status != 200:
            raise JourneyError(f"image upload returned {response.status}")
    completed = request_json(
        "POST", f"/v1/artifacts/{artifact_id}/complete", {"parts": []}, token, timeout=180
    )
    if completed["scan_status"] != "clean":
        raise JourneyError(f"input image was not verified: {completed!r}")
    return dict(completed)


def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    provider_token, _provider_id = register(f"media-provider-{suffix}@example.com")
    publisher_token, _publisher_id = register(f"media-publisher-{suffix}@example.com")
    provider_before = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
    publisher_before = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
    agent = request_json(
        "POST",
        "/v1/agents",
        {"name": "Real Pillow Media Agent", "slug": f"real-media-{suffix}"},
        provider_token,
    )
    agent_id = str(agent["id"])
    credential = str(
        request_json(
            "POST", f"/v1/agents/{agent_id}/credentials", {}, provider_token
        )["credential"]
    )
    request_json(
        "POST", f"/v1/agents/{agent_id}/endpoints", {"endpoint_type": "pull"}, provider_token
    )
    offering = request_json(
        "POST",
        "/v1/offerings/versions",
        {
            "offering_id": None,
            "slug": f"real-media-edit-{suffix}",
            "agent_id": agent_id,
            "schema_id": "image.edit",
            "schema_version": "1.0",
            "name_i18n": {"en": "Pillow Image Edit", "zh": "Pillow 图片编辑"},
            "description_i18n": {
                "en": "Applies a visible border and label to a real image.",
                "zh": "为真实图片添加可见边框和标签。",
            },
            "capabilities": ["pillow", "preserve-dimensions"],
            "risk_disclosure": "Deterministic Pillow transformation; no model is claimed.",
            "output_license": "publisher-use",
            "sla_seconds": 600,
            "input_limits": {"max_pixels": 16_777_216},
            "estimated_tokens_min": 1000,
            "estimated_tokens_max": 4000,
            "estimated_seconds_min": 1,
            "estimated_seconds_max": 120,
            "auto_apply_policy": {"enabled": False},
        },
        provider_token,
    )
    version_id = str(offering["version_id"])
    environment = os.environ.copy()
    python_path = str(ROOT / "sdk" / "python" / "src")
    if environment.get("PYTHONPATH"):
        python_path = f"{python_path}{os.pathsep}{environment['PYTHONPATH']}"
    environment.update(
        {
            "WORKWORLD_API_URL": API_URL,
            "WORKWORLD_AGENT_CREDENTIAL": credential,
            "PYTHONPATH": python_path,
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "examples" / "python-media-echo-agent" / "agent.py")],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(
            "media endpoint and capacity",
            lambda: request_json("GET", f"/v1/agents/{agent_id}", token=provider_token),
            lambda value: (
                (value.get("capacity") or {}).get("status") == "online"
                and any(row.get("status") == "verified" for row in value["endpoints"])
            ),
            process=process,
            timeout=60,
        )
        certification = request_json(
            "POST",
            f"/v1/offerings/versions/{version_id}/certify",
            {},
            provider_token,
            timeout=360,
        )
        if certification["status"] != "passed" or len(certification["checks"]) != 11:
            raise JourneyError(f"media certification failed: {certification!r}")
        request_json(
            "POST", f"/v1/offerings/versions/{version_id}/publish", {}, provider_token
        )
        task = request_json(
            "POST",
            "/v1/tasks",
            {
                "schema_id": "image.edit",
                "schema_version": "1.0",
                "title": "Real Pillow image edit",
                "public_summary": "Transform a real PNG through the Artifact pipeline.",
                "input_json": {
                    "instruction": "Add a red border and WorkWorld label.",
                    "preserve_dimensions": True,
                    "difficulty": "simple",
                },
                "field_visibility": {"instruction": "winner"},
                "difficulty": "simple",
                "acceptance_rules": {"preserve_dimensions": True},
                "budget_tokens": 10_000,
                "recruitment_deadline": None,
                "completion_deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "assignment_mode": "recommended",
                "data_disclosure_acknowledged": True,
            },
            publisher_token,
        )
        task_id = str(task["id"])
        source = io.BytesIO()
        Image.new("RGB", (128, 128), color="blue").save(source, format="PNG")
        input_artifact = upload_input(publisher_token, task_id, source.getvalue())
        detail = request_json("GET", f"/v1/tasks/{task_id}", token=publisher_token)
        if version_id not in {
            row["offering_version_id"] for row in detail["recommendations"]
        }:
            raise JourneyError(f"media Offering was not recommended: {detail!r}")
        selected = request_json(
            "POST",
            f"/v1/tasks/{task_id}/offerings/{version_id}/select",
            {},
            publisher_token,
        )
        run_id = str(selected["run_id"])
        evaluated = wait_for(
            "media result evaluation",
            lambda: request_json("GET", f"/v1/runs/{run_id}", token=publisher_token),
            lambda value: value.get("state") == "waiting_for_acceptance",
            process=process,
            timeout=120,
        )
        artifacts = evaluated["artifacts"]
        inputs = [row for row in artifacts if row["direction"] == "input"]
        outputs = [row for row in artifacts if row["direction"] == "output"]
        if len(inputs) != 1 or len(outputs) != 1:
            raise JourneyError(f"media Artifact directions invalid: {artifacts!r}")
        if inputs[0]["id"] != input_artifact["id"]:
            raise JourneyError("media input Artifact identity changed")
        for artifact in (inputs[0], outputs[0]):
            if artifact["scan_status"] != "clean" or artifact["metadata"].get("pixels") != 16384:
                raise JourneyError(f"media Artifact was not measured: {artifact!r}")
        download = request_json(
            "GET", f"/v1/artifacts/{outputs[0]['id']}/download", token=publisher_token
        )
        with urllib.request.urlopen(str(download["url"]), timeout=60) as response:
            output_bytes = response.read()
        with Image.open(io.BytesIO(output_bytes)) as output_image:
            rgb = output_image.convert("RGB")
            if output_image.size != (128, 128) or rgb.getpixel((8, 8)) != (255, 0, 0):
                raise JourneyError("downloaded media output lacks the requested visible transform")
        accepted = request_json("POST", f"/v1/runs/{run_id}/accept", {}, publisher_token)
        measured = int(evaluated["measured_tokens"])
        provider_after = request_json("GET", "/v1/wallet", token=provider_token)["balances"]
        publisher_after = request_json("GET", "/v1/wallet", token=publisher_token)["balances"]
        if accepted["settled_tokens"] != measured or measured <= 0:
            raise JourneyError(f"media settlement mismatch: {accepted!r}")
        if provider_after["provider_available"] - provider_before["provider_available"] != measured:
            raise JourneyError("media provider settlement mismatch")
        if publisher_before["user_available"] - publisher_after["user_available"] != measured:
            raise JourneyError("media publisher settlement/refund mismatch")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "schema": "image.edit@1.0",
                    "certification_checks": len(certification["checks"]),
                    "input_artifact": inputs[0]["id"],
                    "output_artifact": outputs[0]["id"],
                    "minio_clamav": True,
                    "dimensions": [128, 128],
                    "evaluation_mode": evaluated["evaluation"]["mode"],
                    "settled_tokens": measured,
                },
                sort_keys=True,
            )
        )
    finally:
        stop_process(process)


if __name__ == "__main__":
    try:
        main()
    except JourneyError as exc:
        print(f"real media journey failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
