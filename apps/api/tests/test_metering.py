from decimal import Decimal

import pytest
from workworld_api.services.metering import quality_multiplier, settled_tokens, unit_quantity


@pytest.mark.parametrize(
    ("unit", "document", "metadata", "expected"),
    [
        ("text_token", {"text": "one two"}, [], Decimal(2)),
        ("json_node", {"a": [1, 2]}, [], Decimal(4)),
        ("finding", {"findings": ["a", "b"]}, [], Decimal(2)),
        ("megapixel", {}, [{"pixels": 2_000_000}], Decimal(2)),
        ("document_page", {}, [{"page_count": 3}], Decimal(3)),
        ("nonempty_cell", {}, [{"nonempty_cell_upper_bound": 25}], Decimal(25)),
        ("audio_second", {}, [{"duration_seconds": 12.5}], Decimal("12.5")),
        ("video_second", {}, [{"duration_seconds": 9}], Decimal(9)),
        ("archive_file", {}, [{"file_count": 7}], Decimal(7)),
        (
            "uncompressed_megabyte",
            {},
            [{"uncompressed_size_bytes": 2 * 1_048_576}],
            Decimal(2),
        ),
        ("code_line", {}, [{"code_line_count": 120}], Decimal(120)),
    ],
)
def test_all_catalog_metering_units_have_deterministic_measurement(
    unit: str,
    document: object,
    metadata: list[dict[str, object]],
    expected: Decimal,
) -> None:
    assert unit_quantity(unit, document, metadata) == expected


def test_quality_bounds_rounding_and_budget_cap() -> None:
    assert quality_multiplier(0) == Decimal("0.7")
    assert quality_multiplier(100) == Decimal("1.300")
    with pytest.raises(ValueError, match="quality_score_out_of_range"):
        quality_multiplier(101)
    assert (
        settled_tokens(
            base_tokens=100,
            input_unit="text_token",
            output_unit="text_token",
            input_document={"text": "one two"},
            output_document={"text": "three"},
            input_metadata=[],
            output_metadata=[],
            difficulty_multiplier=1.0,
            quality_score=50,
            budget=50,
        )
        == 50
    )
