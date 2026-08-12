import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

UNIT_RATES = {
    "text_token": Decimal("1"),
    "megapixel": Decimal("500"),
    "document_page": Decimal("100"),
    "nonempty_cell": Decimal("0.2"),
    "audio_second": Decimal("4"),
    "video_second": Decimal("8"),
    "archive_file": Decimal("10"),
    "uncompressed_megabyte": Decimal("20"),
    "code_line": Decimal("0.5"),
    "finding": Decimal("50"),
    "json_node": Decimal("0.1"),
}


def _walk(value: Any) -> tuple[int, int, int]:
    if isinstance(value, dict):
        children = [_walk(item) for item in value.values()]
        return (
            1 + sum(item[0] for item in children),
            sum(item[1] for item in children),
            sum(item[2] for item in children),
        )
    if isinstance(value, list):
        children = [_walk(item) for item in value]
        return (
            1 + sum(item[0] for item in children),
            sum(item[1] for item in children),
            len(value) + sum(item[2] for item in children),
        )
    if isinstance(value, str):
        return 1, len(re.findall(r"[\w]+|[^\s\w]", value, flags=re.UNICODE)), 0
    return 1, 0, 0


def unit_quantity(unit: str, document: Any, metadata: list[dict[str, Any]]) -> Decimal:
    nodes, tokens, array_items = _walk(document)
    if unit == "text_token":
        return Decimal(tokens + sum(int(item.get("token_count", 0)) for item in metadata))
    if unit == "json_node":
        return Decimal(nodes + sum(int(item.get("node_count", 0)) for item in metadata))
    if unit == "finding":
        return Decimal(array_items)
    key = {
        "megapixel": "pixels",
        "document_page": "page_count",
        "nonempty_cell": "nonempty_cell_upper_bound",
        "audio_second": "duration_seconds",
        "video_second": "duration_seconds",
        "archive_file": "file_count",
        "uncompressed_megabyte": "uncompressed_size_bytes",
        "code_line": "code_line_count",
    }.get(unit)
    if key is None:
        raise ValueError("metering_unit_unknown")
    quantity = sum(
        (Decimal(str(item.get(key, 0))) for item in metadata), start=Decimal(0)
    )
    if unit == "megapixel":
        quantity /= Decimal(1_000_000)
    elif unit == "uncompressed_megabyte":
        quantity /= Decimal(1_048_576)
    return quantity


def quality_multiplier(score: int) -> Decimal:
    if not 0 <= score <= 100:
        raise ValueError("quality_score_out_of_range")
    return Decimal("0.7") + Decimal(score) * Decimal("0.006")


def settled_tokens(
    *,
    base_tokens: int,
    input_unit: str,
    output_unit: str,
    input_document: Any,
    output_document: Any,
    input_metadata: list[dict[str, Any]],
    output_metadata: list[dict[str, Any]],
    difficulty_multiplier: float,
    quality_score: int,
    budget: int,
) -> int:
    input_work = unit_quantity(input_unit, input_document, input_metadata) * UNIT_RATES[input_unit]
    output_work = (
        unit_quantity(output_unit, output_document, output_metadata) * UNIT_RATES[output_unit]
    )
    amount = (
        (Decimal(base_tokens) + input_work + output_work)
        * Decimal(str(difficulty_multiplier))
        * quality_multiplier(quality_score)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return min(budget, max(0, int(amount)))
