import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

CATALOG_PATH = Path(__file__).parents[4] / "schemas" / "tasks" / "catalog.json"


@lru_cache
def load_catalog() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def get_schema(schema_id: str, version: str) -> dict[str, Any] | None:
    for definition in load_catalog()["schemas"]:
        if definition["id"] == schema_id and definition["version"] == version:
            return cast(dict[str, Any], definition)
    return None
