import pytest
from workworld_api.ids import new_id


@pytest.mark.parametrize(
    "prefix",
    [
        "artifact",
        "recommendation",
        "application",
        "clarification",
        "transaction",
        "capacity",
        "connection",
        "offering_version",
    ],
)
def test_generated_ids_preserve_prefix_and_fit_shortest_database_column(
    prefix: str,
) -> None:
    identifiers = {new_id(prefix) for _ in range(100)}

    assert len(identifiers) == 100
    assert all(identifier.startswith(f"{prefix}_") for identifier in identifiers)
    assert all(len(identifier) <= 40 for identifier in identifiers)
