from workworld_api.domain.visibility import visible_input


def test_unspecified_fields_are_winner_only_by_secure_default() -> None:
    values = {"title": "Public", "details": "Applicants", "secret": "Winner"}
    levels = {"title": "public", "details": "applicants"}
    assert visible_input(values, levels, "public") == {"title": "Public"}  # type: ignore[arg-type]
    assert visible_input(values, levels, "applicants") == {  # type: ignore[arg-type]
        "title": "Public",
        "details": "Applicants",
    }
    assert visible_input(values, levels, "winner") == values  # type: ignore[arg-type]
