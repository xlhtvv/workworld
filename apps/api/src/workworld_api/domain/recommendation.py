from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    offering_version_id: str
    published: bool
    schema_id: str
    schema_version: str
    input_within_limits: bool
    available: bool
    capacity_available: bool
    estimated_tokens_max: int
    estimated_seconds_max: int
    quality_score: float
    reliability_score: float
    user_rating_score: float


@dataclass(frozen=True)
class RankedCandidate:
    offering_version_id: str
    score: float
    explanation: dict[str, float]


def recommend(
    candidates: list[Candidate],
    *,
    schema_id: str,
    schema_version: str,
    budget_tokens: int,
    completion_seconds: int,
    limit: int = 3,
) -> list[RankedCandidate]:
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        if not (
            candidate.published
            and candidate.schema_id == schema_id
            and candidate.schema_version == schema_version
            and candidate.input_within_limits
            and candidate.available
            and candidate.capacity_available
            and candidate.estimated_tokens_max <= budget_tokens
            and candidate.estimated_seconds_max <= completion_seconds
        ):
            continue
        budget_fit = max(0.0, 1 - candidate.estimated_tokens_max / max(budget_tokens, 1))
        components = {
            "schema_capability_match": 1.0,
            "automated_quality": _bounded(candidate.quality_score),
            "on_time_availability": _bounded(candidate.reliability_score),
            "user_rating": _bounded(candidate.user_rating_score),
            "token_budget_fit": budget_fit,
        }
        score = (
            components["schema_capability_match"] * 0.45
            + components["automated_quality"] * 0.20
            + components["on_time_availability"] * 0.15
            + components["user_rating"] * 0.10
            + components["token_budget_fit"] * 0.10
        )
        ranked.append(RankedCandidate(candidate.offering_version_id, round(score, 6), components))
    return sorted(ranked, key=lambda item: (-item.score, item.offering_version_id))[:limit]


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))
