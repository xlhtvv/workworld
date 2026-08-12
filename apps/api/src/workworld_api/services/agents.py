import hashlib
import hmac
import json
import re
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.ids import new_id
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentCredential,
    AgentEndpoint,
    Offering,
    OfferingCertification,
    OfferingVersion,
)
from workworld_api.models import Artifact, User
from workworld_api.schema_catalog import get_schema
from workworld_api.services.certification import is_publishable_certification
from workworld_api.services.endpoint_security import (
    PinnedHTTPSVerifier,
    ValidatedEndpoint,
    configured_endpoint_validator,
    validate_https_endpoint,
)
from workworld_api.services.moderation import ModerationBlocked, ModerationService


class AgentError(ValueError):
    pass


def credential_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise AgentError("invalid_slug")
    return slug


class AgentService:
    def __init__(
        self,
        db: Session,
        endpoint_validator: Callable[[str], ValidatedEndpoint] | None = None,
        push_verifier: Callable[[ValidatedEndpoint, str], None] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.endpoint_validator = endpoint_validator or (
            configured_endpoint_validator(settings.push_allowed_private_hosts)
            if settings is not None
            else validate_https_endpoint
        )
        self.push_verifier = push_verifier or PinnedHTTPSVerifier(
            ca_file=(settings.push_ca_file or None) if settings is not None else None,
            endpoint_validator=self.endpoint_validator,
        ).verify_challenge

    def create(self, owner: User, name: str, slug: str | None = None) -> Agent:
        try:
            ModerationService(self.db).check_text(
                "agent_candidate", f"candidate_{uuid.uuid4().hex}", name
            )
        except ModerationBlocked as exc:
            raise AgentError(str(exc)) from exc
        agent = Agent(
            id=new_id("agent"),
            owner_id=owner.id,
            name=name,
            slug=_slug(slug or name),
            status="active",
            created_at=datetime.now(UTC),
        )
        self.db.add(agent)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AgentError("agent_slug_conflict") from exc
        return agent

    def issue_credential(self, owner: User, agent_id: str) -> tuple[AgentCredential, str]:
        agent = self._owned(owner, agent_id)
        prefix = secrets.token_hex(6)
        raw = f"wwa_{prefix}.{secrets.token_urlsafe(32)}"
        credential = AgentCredential(
            id=new_id("credential"),
            agent_id=agent.id,
            key_prefix=prefix,
            secret_hash=credential_hash(raw),
            created_at=datetime.now(UTC),
        )
        self.db.add(credential)
        self.db.commit()
        return credential, raw

    def authenticate(self, raw: str) -> Agent:
        match = re.fullmatch(r"wwa_([0-9a-f]{12})\..+", raw)
        if match is None:
            raise AgentError("invalid_agent_credential")
        credential = self.db.scalar(
            select(AgentCredential).where(AgentCredential.key_prefix == match.group(1))
        )
        now = datetime.now(UTC)
        if (
            credential is None
            or credential.revoked_at is not None
            or (credential.expires_at is not None and _expired(credential.expires_at, now))
            or not hmac.compare_digest(credential.secret_hash, credential_hash(raw))
        ):
            raise AgentError("invalid_agent_credential")
        agent = credential.agent
        if agent.status != "active":
            raise AgentError("agent_suspended")
        credential.last_used_at = now
        self.db.commit()
        return agent

    def revoke_credential(self, owner: User, credential_id: str) -> None:
        credential = self.db.get(AgentCredential, credential_id)
        if credential is None or credential.agent.owner_id != owner.id:
            raise AgentError("credential_not_found")
        credential.revoked_at = datetime.now(UTC)
        self.db.commit()

    def register_pull_endpoint(self, owner: User, agent_id: str) -> AgentEndpoint:
        agent = self._owned(owner, agent_id)
        endpoint = AgentEndpoint(
            id=new_id("endpoint"),
            agent_id=agent.id,
            endpoint_type="pull",
            url=None,
            status="pending",
            resolved_addresses=[],
            created_at=datetime.now(UTC),
        )
        self.db.add(endpoint)
        self.db.commit()
        return endpoint

    def register_push_endpoint(self, owner: User, agent_id: str, url: str) -> AgentEndpoint:
        agent = self._owned(owner, agent_id)
        validated = self.endpoint_validator(url)
        challenge = secrets.token_urlsafe(32)
        endpoint = AgentEndpoint(
            id=new_id("endpoint"),
            agent_id=agent.id,
            endpoint_type="push",
            url=validated.url,
            status="pending",
            resolved_addresses=sorted(validated.addresses),
            challenge_hash=credential_hash(challenge),
            challenge_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            created_at=datetime.now(UTC),
        )
        self.db.add(endpoint)
        self.db.commit()
        try:
            self.push_verifier(validated, challenge)
        except ValueError as exc:
            endpoint.status = "failed"
            self.db.commit()
            raise AgentError("endpoint_challenge_failed") from exc
        endpoint.status = "verified"
        endpoint.challenge_hash = None
        endpoint.challenge_expires_at = None
        endpoint.verified_at = datetime.now(UTC)
        self.db.commit()
        return endpoint

    def capacity(
        self,
        agent: Agent,
        *,
        status: str,
        max_concurrent_runs: int,
        active_runs: int,
        queue_capacity: int,
        estimated_wait_seconds: int,
        supported_offering_versions: list[str],
    ) -> AgentCapacitySnapshot:
        if status not in {"online", "offline", "draining"}:
            raise AgentError("capacity_status_invalid")
        if min(max_concurrent_runs, active_runs, queue_capacity, estimated_wait_seconds) < 0:
            raise AgentError("capacity_negative")
        if active_runs > max_concurrent_runs:
            raise AgentError("active_runs_exceed_capacity")
        snapshot = AgentCapacitySnapshot(
            id=new_id("capacity"),
            agent_id=agent.id,
            status=status,
            max_concurrent_runs=max_concurrent_runs,
            active_runs=active_runs,
            queue_capacity=queue_capacity,
            estimated_wait_seconds=estimated_wait_seconds,
            supported_offering_versions=supported_offering_versions,
            observed_at=datetime.now(UTC),
        )
        self.db.add(snapshot)
        self.db.commit()
        return snapshot

    def _owned(self, owner: User, agent_id: str) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.owner_id != owner.id:
            raise AgentError("agent_not_found")
        return agent

    def get_active(self, agent_id: str) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.status != "active":
            raise AgentError("agent_not_found")
        return agent


class OfferingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_version(
        self,
        owner: User,
        agent_id: str,
        slug: str,
        definition: dict[str, Any],
        offering_id: str | None = None,
    ) -> tuple[Offering, OfferingVersion]:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.owner_id != owner.id:
            raise AgentError("agent_not_found")
        schema_id = str(definition["schema_id"])
        schema_version = str(definition["schema_version"])
        if get_schema(schema_id, schema_version) is None:
            raise AgentError("schema_version_not_found")
        public_text = json.dumps(
            {
                "name": definition["name_i18n"],
                "description": definition["description_i18n"],
                "risk_disclosure": definition["risk_disclosure"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            ModerationService(self.db).check_text(
                "offering_candidate", f"candidate_{uuid.uuid4().hex}", public_text
            )
        except ModerationBlocked as exc:
            raise AgentError(str(exc)) from exc
        example_ids = list(dict.fromkeys(definition.get("example_artifact_ids", [])))
        examples = list(
            self.db.scalars(select(Artifact).where(Artifact.id.in_(example_ids)))
        ) if example_ids else []
        if len(examples) != len(example_ids) or any(
            artifact.owner_id != owner.id
            or artifact.task_id is not None
            or artifact.scan_status != "clean"
            or artifact.deleted_at is not None
            or artifact.storage_key is None
            for artifact in examples
        ):
            raise AgentError("offering_example_artifact_invalid")
        offering = self.db.get(Offering, offering_id) if offering_id else None
        if offering is None:
            offering = Offering(
                id=new_id("offering"),
                agent_id=agent.id,
                owner_id=owner.id,
                slug=_slug(slug),
                status="draft",
                created_at=datetime.now(UTC),
            )
            self.db.add(offering)
            self.db.flush()
        elif offering.owner_id != owner.id or offering.agent_id != agent.id:
            raise AgentError("offering_not_found")
        next_version = (
            self.db.scalar(
                select(func.max(OfferingVersion.version)).where(
                    OfferingVersion.offering_id == offering.id
                )
            )
            or 0
        ) + 1
        canonical = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        version = OfferingVersion(
            id=f"{offering.id}_v{next_version}",
            offering_id=offering.id,
            version=next_version,
            schema_id=schema_id,
            schema_version=schema_version,
            name_i18n=definition["name_i18n"],
            description_i18n=definition["description_i18n"],
            capabilities=definition.get("capabilities", []),
            example_artifact_ids=example_ids,
            risk_disclosure=definition["risk_disclosure"],
            output_license=definition["output_license"],
            sla_seconds=definition["sla_seconds"],
            input_limits=definition.get("input_limits", {}),
            estimated_tokens_min=definition["estimated_tokens_min"],
            estimated_tokens_max=definition["estimated_tokens_max"],
            estimated_seconds_min=definition["estimated_seconds_min"],
            estimated_seconds_max=definition["estimated_seconds_max"],
            auto_apply_policy=definition.get("auto_apply_policy", {}),
            status="draft",
            content_sha256=hashlib.sha256(canonical).hexdigest(),
            created_at=datetime.now(UTC),
        )
        self.db.add(version)
        offering.latest_version_id = version.id
        self.db.commit()
        return offering, version

    def publish(self, owner: User, version_id: str) -> OfferingVersion:
        version = self.db.get(OfferingVersion, version_id)
        offering = self.db.get(Offering, version.offering_id) if version else None
        if version is None or offering is None or offering.owner_id != owner.id:
            raise AgentError("offering_version_not_found")
        certification = self.db.scalar(
            select(OfferingCertification)
            .where(
                OfferingCertification.offering_version_id == version.id,
                OfferingCertification.status == "passed",
                OfferingCertification.level == "capability_verified",
            )
            .order_by(OfferingCertification.completed_at.desc())
        )
        verified_endpoint = self.db.scalar(
            select(AgentEndpoint).where(
                AgentEndpoint.agent_id == offering.agent_id,
                AgentEndpoint.status == "verified",
            )
        )
        if (
            certification is None
            or not is_publishable_certification(certification)
            or verified_endpoint is None
        ):
            raise AgentError("offering_not_certified")
        version.status = "published"
        version.published_at = datetime.now(UTC)
        offering.status = "published"
        self.db.commit()
        return version


def _expired(value: datetime, now: datetime) -> bool:
    comparable_now = now if value.tzinfo is not None else now.replace(tzinfo=None)
    return value < comparable_now
