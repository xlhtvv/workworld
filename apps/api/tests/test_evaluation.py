import base64
import hashlib
import io
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.models import Artifact
from workworld_api.services.evaluation import EvaluationError, EvaluationService


def image_artifact(payload: bytes) -> Artifact:
    digest = hashlib.sha256(payload).hexdigest()
    return Artifact(
        id="artifact_image",
        owner_id="user_1",
        task_id="task_1",
        direction="output",
        kind="image",
        mime_type="image/png",
        original_name="result.png",
        size_bytes=len(payload),
        sha256=digest,
        storage_key="clean/task_1/result.png",
        multipart_upload_id=None,
        expected_size_bytes=len(payload),
        expected_sha256=digest,
        declared_mime_type="image/png",
        scan_status="clean",
        metadata_json={"width": 4, "height": 3},
        created_at=datetime.now(UTC),
    )


def test_openai_image_material_is_loaded_and_integrity_checked() -> None:
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), color=(12, 34, 56)).save(stream, format="PNG")
    payload = stream.getvalue()
    artifact = image_artifact(payload)
    settings = Settings(evaluation_mode="openai", openai_api_key="test-key")
    with Session(create_engine("sqlite+pysqlite://")) as db:
        service = EvaluationService(db, settings, artifact_loader=lambda _key: payload)
        inputs = service._image_inputs([artifact])
        assert inputs[0]["artifact_id"] == artifact.id
        encoded = inputs[0]["data_url"].removeprefix("data:image/png;base64,")
        assert base64.b64decode(encoded) == payload

        tampered = EvaluationService(db, settings, artifact_loader=lambda _key: payload + b"x")
        with pytest.raises(EvaluationError, match="evaluation_artifact_integrity_failed"):
            tampered._image_inputs([artifact])
