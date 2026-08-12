from typing import Any, cast
from urllib.parse import urlparse

import pytest
from botocore.client import BaseClient  # type: ignore[import-untyped]
from pydantic import ValidationError
from workworld_api.routers.artifacts import CompleteUpload
from workworld_api.services.s3_store import S3ArtifactStore


def test_presigned_urls_use_public_endpoint_while_operations_keep_internal_client() -> None:
    store = S3ArtifactStore(
        "http://minio:9000",
        "workworld",
        "secret",
        "artifacts",
        "http://localhost:9000",
    )
    part = store.signed_part("quarantine/user/artifact", "upload-id", 1, 300)
    download = store.signed_download("artifacts/user/artifact", 300)
    assert urlparse(part).netloc == "localhost:9000"
    assert urlparse(download).netloc == "localhost:9000"
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in part
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in download
    assert store.client.meta.endpoint_url == "http://minio:9000"


def test_server_can_reconstruct_authoritative_multipart_etags() -> None:
    class Client:
        def list_parts(self, **arguments: Any) -> dict[str, object]:
            assert arguments["UploadId"] == "upload-id"
            return {
                "Parts": [
                    {"PartNumber": 1, "ETag": '"etag-one"'},
                    {"PartNumber": 2, "ETag": '"etag-two"'},
                ],
                "IsTruncated": False,
            }

    store = object.__new__(S3ArtifactStore)
    store.bucket = "artifacts"
    store.client = cast(BaseClient, Client())
    assert store.uploaded_parts("key", "upload-id") == [
        {"PartNumber": 1, "ETag": '"etag-one"'},
        {"PartNumber": 2, "ETag": '"etag-two"'},
    ]


def test_multipart_completion_contract_rejects_duplicate_or_unstructured_parts() -> None:
    assert CompleteUpload(parts=[]).parts == []
    with pytest.raises(ValidationError, match="multipart_part_number_invalid"):
        CompleteUpload(
            parts=[
                {"PartNumber": 1, "ETag": "one"},
                {"PartNumber": 1, "ETag": "duplicate"},
            ]
        )
    with pytest.raises(ValidationError, match="multipart_part_fields_invalid"):
        CompleteUpload(parts=[{"PartNumber": 1, "ETag": "one", "extra": True}])
