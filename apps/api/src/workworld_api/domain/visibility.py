from collections.abc import Mapping
from typing import Any, Literal

Audience = Literal["public", "applicants", "winner"]
RANK: dict[Audience, int] = {"public": 0, "applicants": 1, "winner": 2}


def visible_input(
    values: dict[str, Any], field_visibility: Mapping[str, str], audience: Audience
) -> dict[str, Any]:
    audience_rank = RANK[audience]
    visible: dict[str, Any] = {}
    for key, value in values.items():
        raw_level = field_visibility.get(key, "winner")
        level: Audience = raw_level if raw_level in RANK else "winner"
        if RANK[level] <= audience_rank:
            visible[key] = value
    return visible
