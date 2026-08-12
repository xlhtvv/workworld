import pytest
from workworld_api.domain.run_state import (
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidRunTransition,
    RunState,
    ensure_transition,
)


def test_every_state_is_explicitly_defined() -> None:
    assert set(TRANSITIONS) == set(RunState)


@pytest.mark.parametrize("state", TERMINAL_STATES)
def test_terminal_states_have_no_exit(state: RunState) -> None:
    assert TRANSITIONS[state] == frozenset()


def test_agent_cannot_complete_a_running_run() -> None:
    with pytest.raises(InvalidRunTransition):
        ensure_transition(RunState.RUNNING, RunState.COMPLETED)


def test_result_must_be_evaluated_before_acceptance() -> None:
    ensure_transition(RunState.RESULT_SUBMITTED, RunState.EVALUATING)
    ensure_transition(RunState.EVALUATING, RunState.WAITING_FOR_ACCEPTANCE)
    ensure_transition(RunState.WAITING_FOR_ACCEPTANCE, RunState.COMPLETED)


def test_cancel_is_free_before_acceptance() -> None:
    for state in (RunState.DRAFT, RunState.OPEN, RunState.MATCHING, RunState.OFFER_SENT):
        assert RunState.CANCELLED in TRANSITIONS[state]
