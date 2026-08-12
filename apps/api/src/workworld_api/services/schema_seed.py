import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session
from workworld_api.models import SchemaDefinition, SchemaVersion
from workworld_api.schema_catalog import load_catalog


class PublishedSchemaChanged(RuntimeError):
    pass


def _canonical_hash(definition: dict[str, object]) -> str:
    encoded = json.dumps(
        definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def seed_catalog(db: Session) -> int:
    created = 0
    now = datetime.now(UTC)
    for definition in load_catalog()["schemas"]:
        schema_id = str(definition["id"])
        version = str(definition["version"])
        version_id = f"{schema_id}@{version}"
        digest = _canonical_hash(definition)
        existing = db.get(SchemaVersion, version_id)
        if existing is not None:
            if existing.content_sha256 != digest:
                raise PublishedSchemaChanged(version_id)
            continue
        if db.get(SchemaDefinition, schema_id) is None:
            db.add(SchemaDefinition(id=schema_id, created_at=now))
            db.flush()
        db.add(
            SchemaVersion(
                id=version_id,
                schema_id=schema_id,
                version=version,
                status="published",
                definition_json=definition,
                content_sha256=digest,
                published_at=now,
            )
        )
        created += 1
    db.commit()
    return created
