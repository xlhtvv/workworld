import logging
from collections.abc import Iterator
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)
S3_CLIENT_CONFIG = Config(signature_version="s3v4", s3={"addressing_style": "path"})


class S3ArtifactStore:
    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=S3_CLIENT_CONFIG,
        )
        self.signing_client: BaseClient = (
            boto3.client(
                "s3",
                endpoint_url=public_endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="us-east-1",
                config=S3_CLIENT_CONFIG,
            )
            if public_endpoint_url and public_endpoint_url != endpoint_url
            else self.client
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self.client.exceptions.ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def check(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def begin_multipart(self, key: str, mime_type: str) -> str:
        result = self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, ContentType=mime_type
        )
        return str(result["UploadId"])

    def signed_part(self, key: str, upload_id: str, part_number: int, ttl: int) -> str:
        if not 1 <= part_number <= 10_000:
            raise ValueError("invalid_part_number")
        return str(
            self.signing_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=ttl,
            )
        )

    def complete(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> None:
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def uploaded_parts(self, key: str, upload_id: str) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        marker = 0
        while True:
            response = self.client.list_parts(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                PartNumberMarker=marker,
                MaxParts=1000,
            )
            page = response.get("Parts", [])
            parts.extend(
                {"PartNumber": int(item["PartNumber"]), "ETag": str(item["ETag"])}
                for item in page
            )
            if len(parts) > 10_000:
                raise ValueError("multipart_part_limit")
            if not response.get("IsTruncated"):
                break
            marker = int(response["NextPartNumberMarker"])
        if not parts:
            raise ValueError("multipart_parts_missing")
        return parts

    def chunks(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        yield from iter(lambda: body.read(CHUNK_SIZE), b"")

    def copy(self, source_key: str, target_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            Key=target_key,
            CopySource={"Bucket": self.bucket, "Key": source_key},
        )

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError:
            logger.warning("failed to delete superseded object key=%s", key, exc_info=True)
            return False
        return True

    def signed_download(self, key: str, ttl: int) -> str:
        return str(
            self.signing_client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl
            )
        )


CHUNK_SIZE = 1024 * 1024
