"""Register the complete ORM metadata before any isolated test creates tables."""

from workworld_api import (  # noqa: F401
    finance_models,
    market_models,
    models,
    reputation_models,
    task_models,
)
