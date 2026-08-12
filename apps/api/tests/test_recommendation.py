from workworld_api.domain.recommendation import Candidate, recommend


def candidate(identifier: str, **changes: object) -> Candidate:
    values = {
        "offering_version_id": identifier,
        "published": True,
        "schema_id": "text.summarize",
        "schema_version": "1.0",
        "input_within_limits": True,
        "available": True,
        "capacity_available": True,
        "estimated_tokens_max": 500,
        "estimated_seconds_max": 60,
        "quality_score": 0.8,
        "reliability_score": 0.9,
        "user_rating_score": 0.7,
    }
    values.update(changes)
    return Candidate(**values)  # type: ignore[arg-type]


def test_hard_filters_exclude_every_ineligible_dimension() -> None:
    eligible = candidate("eligible")
    rejected = [
        candidate("draft", published=False),
        candidate("schema", schema_id="json.transform"),
        candidate("version", schema_version="2.0"),
        candidate("limits", input_within_limits=False),
        candidate("offline", available=False),
        candidate("full", capacity_available=False),
        candidate("expensive", estimated_tokens_max=1001),
        candidate("late", estimated_seconds_max=601),
    ]
    result = recommend(
        [eligible, *rejected],
        schema_id="text.summarize",
        schema_version="1.0",
        budget_tokens=1000,
        completion_seconds=600,
    )
    assert [item.offering_version_id for item in result] == ["eligible"]


def test_weighted_score_is_explainable_and_top_three_deterministic() -> None:
    result = recommend(
        [
            candidate("quality", quality_score=1.0, user_rating_score=1.0),
            candidate("reliable", reliability_score=1.0),
            candidate("cheap", estimated_tokens_max=100),
            candidate("fourth", quality_score=0.1, reliability_score=0.1),
        ],
        schema_id="text.summarize",
        schema_version="1.0",
        budget_tokens=1000,
        completion_seconds=600,
    )
    assert len(result) == 3
    assert result[0].offering_version_id == "quality"
    assert set(result[0].explanation) == {
        "schema_capability_match",
        "automated_quality",
        "on_time_availability",
        "user_rating",
        "token_budget_fit",
    }
