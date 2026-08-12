from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.models import SchemaVersion
from workworld_api.services.schema_seed import seed_catalog


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_seed_is_idempotent_and_persists_all_versions(db: Session) -> None:
    assert seed_catalog(db) == 12
    assert seed_catalog(db) == 0
    assert db.query(SchemaVersion).count() == 12


def test_published_schema_cannot_be_changed_in_place(db: Session) -> None:
    seed_catalog(db)
    version = db.get(SchemaVersion, "text.generate@1.0")
    assert version is not None
    version.content_sha256 = "0" * 64
    with pytest.raises(ValueError, match="published_schema_version_is_immutable"):
        db.commit()
    db.rollback()


def test_published_schema_cannot_be_deleted(db: Session) -> None:
    seed_catalog(db)
    version = db.get(SchemaVersion, "text.summarize@1.0")
    assert version is not None
    db.delete(version)
    with pytest.raises(ValueError, match="published_schema_version_is_immutable"):
        db.commit()
    db.rollback()
