from workworld_api.config import Settings
from workworld_api.services.rate_limit import request_policy


def test_rate_limit_policies_separate_auth_agents_and_mutations() -> None:
    settings = Settings(
        rate_limit_auth_requests=11,
        rate_limit_agent_requests=22,
        rate_limit_mutation_requests=33,
    )
    assert request_policy("GET", "/v1/tasks", settings) is None
    assert request_policy("POST", "/health", settings) is None
    assert request_policy("POST", "/v1/auth/login", settings).limit == 11  # type: ignore[union-attr]
    assert request_policy("POST", "/v1/agent-auth/token", settings).group == "agent-auth"  # type: ignore[union-attr]
    assert request_policy("POST", "/v1/agent-callbacks/events", settings).limit == 22  # type: ignore[union-attr]
    assert request_policy("POST", "/v1/tasks", settings).limit == 33  # type: ignore[union-attr]
