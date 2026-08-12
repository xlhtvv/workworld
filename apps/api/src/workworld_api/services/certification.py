import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.market_models import (
    AgentEndpoint,
    Offering,
    OfferingCertification,
    OfferingVersion,
)
from workworld_api.models import Artifact, ScanStatus, User
from workworld_api.schema_catalog import get_schema
from workworld_api.services.endpoint_security import (
    PinnedHTTPSVerifier,
    UnsafeEndpoint,
    ValidatedEndpoint,
    configured_endpoint_validator,
)
from workworld_api.services.pull_certification import PullCertificationUnavailable

SUITE_VERSION = "1.0"
REQUIRED_CHECKS = frozenset(
    {
        "handshake",
        "schema_consistency",
        "accept",
        "reject",
        "progress",
        "clarification",
        "cancel",
        "timeout",
        "idempotency",
        "artifact_upload",
        "output_validation",
    }
)


class CertificationError(ValueError):
    pass


Sender = Callable[[ValidatedEndpoint, object, str], tuple[int, bytes]]
Validator = Callable[[str], ValidatedEndpoint]


def digest(value: object) -> str:
    if isinstance(value, bytes):
        encoded = value
    else:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    return hashlib.sha256(encoded).hexdigest()


class OfferingCertificationService:
    """Run one platform-originated suite over a verified Pull or Push endpoint."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        endpoint_type: Literal["pull", "push"] = "push",
        validator: Validator | None = None,
        sender: Sender | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.endpoint_type = endpoint_type
        self.validator = validator or configured_endpoint_validator(
            settings.push_allowed_private_hosts
        )
        self.sender = sender or (
            PinnedHTTPSVerifier(
                ca_file=settings.push_ca_file or None,
                endpoint_validator=self.validator,
            ).post_signed_json
            if endpoint_type == "push"
            else None
        )

    def run(self, owner: User, version_id: str) -> OfferingCertification:
        version = self.db.get(OfferingVersion, version_id)
        offering = self.db.get(Offering, version.offering_id) if version else None
        if (
            version is None
            or offering is None
            or offering.owner_id != owner.id
            or version.status != "draft"
        ):
            raise CertificationError("offering_version_not_certifiable")
        endpoint = self.db.scalar(
            select(AgentEndpoint).where(
                AgentEndpoint.agent_id == offering.agent_id,
                AgentEndpoint.endpoint_type == self.endpoint_type,
                AgentEndpoint.status == "verified",
            )
        )
        if endpoint is None or (self.endpoint_type == "push" and endpoint.url is None):
            raise CertificationError(f"verified_{self.endpoint_type}_endpoint_required")
        if self.sender is None:
            raise CertificationError("certification_transport_required")
        schema = get_schema(version.schema_id, version.schema_version)
        if schema is None:
            raise CertificationError("schema_version_not_found")

        certification_id = f"certification_{uuid.uuid4().hex}"
        challenges = {name: secrets.token_urlsafe(24) for name in REQUIRED_CHECKS}
        artifact_bytes = challenges["artifact_upload"].encode()
        sample_input = _sample(schema["input_schema"])
        request = {
            "type": "offering.certification",
            "certification_id": certification_id,
            "test_suite_version": SUITE_VERSION,
            "offering_version_id": version.id,
            "schema_id": version.schema_id,
            "schema_version": version.schema_version,
            "sample_input": sample_input,
            "artifact_challenge": {
                "content_utf8": challenges["artifact_upload"],
                "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            },
            "scenarios": [
                {"name": name, "challenge": challenges[name]}
                for name in sorted(REQUIRED_CHECKS)
            ],
        }
        started_at = datetime.now(UTC)
        checks: list[dict[str, Any]] = []
        sample_output: object = None
        response_document: object = {"transport_error": True}
        try:
            validated = (
                self.validator(endpoint.url)
                if endpoint.url is not None
                else ValidatedEndpoint("https://pull.invalid", "pull.invalid", 443, frozenset())
            )
            status, response_body = self.sender(
                validated, request, self.settings.push_signing_secret
            )
            if not 200 <= status < 300:
                raise CertificationError("certification_http_error")
            response_document = json.loads(response_body)
            if not isinstance(response_document, dict):
                raise CertificationError("certification_response_invalid")
            if response_document.get("certification_id") != certification_id:
                raise CertificationError("certification_id_mismatch")
            raw_results = response_document.get("results")
            results = raw_results if isinstance(raw_results, list) else []
            observed = {
                str(item.get("name")): item
                for item in results
                if isinstance(item, dict)
            }
            for name in sorted(REQUIRED_CHECKS - {"output_validation", "artifact_upload"}):
                item = observed.get(name, {})
                input_valid = not list(
                    Draft202012Validator(schema["input_schema"]).iter_errors(sample_input)
                )
                checks.append(
                    {
                        "name": name,
                        "passed": item.get("passed") is True
                        and secrets.compare_digest(
                            str(item.get("challenge", "")), challenges[name]
                        )
                        and (name != "schema_consistency" or input_valid),
                    }
                )
            sample_output = response_document.get("sample_output")
            output_errors = sorted(
                error.message
                for error in Draft202012Validator(schema["output_schema"]).iter_errors(
                    sample_output
                )
            )
            checks.append(
                {
                    "name": "output_validation",
                    "passed": not output_errors,
                    "errors": output_errors,
                }
            )
            artifact_id = response_document.get("artifact_id")
            artifact = (
                self.db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
            )
            artifact_passed = (
                artifact is not None
                and artifact.owner_id == owner.id
                and artifact.scan_status == ScanStatus.CLEAN
                and artifact.sha256 == hashlib.sha256(artifact_bytes).hexdigest()
            )
            checks.append({"name": "artifact_upload", "passed": artifact_passed})
        except (
            CertificationError,
            OSError,
            PullCertificationUnavailable,
            UnsafeEndpoint,
            json.JSONDecodeError,
        ) as exc:
            checks = [{"name": name, "passed": False} for name in sorted(REQUIRED_CHECKS)]
            response_document = {"error": type(exc).__name__}

        passed = {str(item["name"]) for item in checks if item.get("passed")} == REQUIRED_CHECKS
        certification = OfferingCertification(
            id=certification_id,
            offering_version_id=version.id,
            test_suite_version=SUITE_VERSION,
            status="passed" if passed else "failed",
            level="capability_verified" if passed else "protocol_verified",
            checks_json=checks,
            input_hash=digest(sample_input),
            output_hash=digest(sample_output) if sample_output is not None else None,
            score=100 * sum(bool(item["passed"]) for item in checks) // len(REQUIRED_CHECKS),
            log_hash=digest({"request": request, "response": response_document}),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        self.db.add(certification)
        self.db.commit()
        return certification


# Backward-compatible internal name for existing callers while the public workflow is
# transport-neutral.
PushCertificationService = OfferingCertificationService


def is_publishable_certification(certification: OfferingCertification) -> bool:
    passed = {
        str(item.get("name"))
        for item in certification.checks_json
        if item.get("passed") is True
    }
    return (
        certification.status == "passed"
        and certification.level == "capability_verified"
        and certification.test_suite_version == SUITE_VERSION
        and passed == REQUIRED_CHECKS
    )


def _sample(schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if schema_type == "object":
        properties = schema.get("properties", {})
        return {name: _sample(properties[name]) for name in schema.get("required", [])}
    if schema_type == "array":
        return [_sample(schema.get("items", {}))]
    if schema_type == "integer":
        return int(schema.get("minimum", 1))
    if schema_type == "number":
        return float(schema.get("minimum", 1))
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None
    return "certification sample"


def certify_transcript(
    db: Session,
    version_id: str,
    transcript: list[dict[str, Any]],
    sample_input: dict[str, Any],
    sample_output: dict[str, Any],
) -> OfferingCertification:
    version = db.get(OfferingVersion, version_id)
    if version is None or version.status != "draft":
        raise CertificationError("offering_version_not_certifiable")
    schema = get_schema(version.schema_id, version.schema_version)
    if schema is None:
        raise CertificationError("schema_version_not_found")
    checks: list[dict[str, Any]] = []
    observed = {str(item.get("check")) for item in transcript if item.get("passed") is True}
    input_errors = sorted(
        error.message
        for error in Draft202012Validator(schema["input_schema"]).iter_errors(sample_input)
    )
    for name in sorted(REQUIRED_CHECKS - {"output_validation"}):
        if name == "schema_consistency":
            checks.append(
                {
                    "name": name,
                    "passed": name in observed and not input_errors,
                    "errors": input_errors,
                }
            )
        else:
            checks.append({"name": name, "passed": name in observed})
    output_errors = sorted(
        error.message
        for error in Draft202012Validator(schema["output_schema"]).iter_errors(sample_output)
    )
    checks.append(
        {"name": "output_validation", "passed": not output_errors, "errors": output_errors}
    )
    passed = all(bool(item["passed"]) for item in checks)
    now = datetime.now(UTC)
    certification = OfferingCertification(
        id=f"certification_{uuid.uuid4().hex}",
        offering_version_id=version.id,
        test_suite_version=SUITE_VERSION,
        status="passed" if passed else "failed",
        level="capability_verified" if passed else "protocol_verified",
        checks_json=checks,
        input_hash=digest(sample_input),
        output_hash=digest(sample_output),
        score=100 * sum(bool(item["passed"]) for item in checks) // len(checks),
        log_hash=digest(transcript),
        started_at=now,
        completed_at=now,
    )
    db.add(certification)
    db.commit()
    return certification
