from enum import StrEnum
from types import MappingProxyType


class RunState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    MATCHING = "matching"
    CANDIDATE_SELECTED = "candidate_selected"
    OFFER_SENT = "offer_sent"
    ACCEPTED = "accepted"
    RUNNING = "running"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    WAITING_FOR_BUDGET = "waiting_for_budget"
    RESULT_SUBMITTED = "result_submitted"
    EVALUATING = "evaluating"
    WAITING_FOR_ACCEPTANCE = "waiting_for_acceptance"
    REWORK_REQUESTED = "rework_requested"
    REWORKING = "reworking"
    COMPLETED = "completed"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    AGENT_UNREACHABLE = "agent_unreachable"


TERMINAL_STATES = frozenset(
    {RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED, RunState.TIMED_OUT}
)

_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.DRAFT: frozenset({RunState.OPEN, RunState.CANCELLED}),
    RunState.OPEN: frozenset({RunState.MATCHING, RunState.CANCELLED, RunState.TIMED_OUT}),
    RunState.MATCHING: frozenset(
        {RunState.CANDIDATE_SELECTED, RunState.OPEN, RunState.CANCELLED, RunState.TIMED_OUT}
    ),
    RunState.CANDIDATE_SELECTED: frozenset(
        {RunState.OFFER_SENT, RunState.OPEN, RunState.CANCELLED, RunState.TIMED_OUT}
    ),
    RunState.OFFER_SENT: frozenset(
        {
            RunState.ACCEPTED,
            RunState.OPEN,
            RunState.CANCELLED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.ACCEPTED: frozenset(
        {
            RunState.RUNNING,
            RunState.CANCELLATION_REQUESTED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.RUNNING: frozenset(
        {
            RunState.WAITING_FOR_CLARIFICATION,
            RunState.WAITING_FOR_BUDGET,
            RunState.RESULT_SUBMITTED,
            RunState.CANCELLATION_REQUESTED,
            RunState.FAILED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.WAITING_FOR_CLARIFICATION: frozenset(
        {
            RunState.RUNNING,
            RunState.CANCELLATION_REQUESTED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.WAITING_FOR_BUDGET: frozenset(
        {
            RunState.RUNNING,
            RunState.RESULT_SUBMITTED,
            RunState.CANCELLATION_REQUESTED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.RESULT_SUBMITTED: frozenset({RunState.EVALUATING}),
    RunState.EVALUATING: frozenset(
        {RunState.WAITING_FOR_ACCEPTANCE, RunState.REWORK_REQUESTED, RunState.FAILED}
    ),
    RunState.WAITING_FOR_ACCEPTANCE: frozenset({RunState.COMPLETED, RunState.REWORK_REQUESTED}),
    RunState.REWORK_REQUESTED: frozenset({RunState.REWORKING}),
    RunState.REWORKING: frozenset(
        {
            RunState.RESULT_SUBMITTED,
            RunState.CANCELLATION_REQUESTED,
            RunState.FAILED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.CANCELLATION_REQUESTED: frozenset(
        {
            RunState.CANCELLED,
            RunState.RESULT_SUBMITTED,
            RunState.TIMED_OUT,
            RunState.AGENT_UNREACHABLE,
        }
    ),
    RunState.AGENT_UNREACHABLE: frozenset(
        {
            RunState.ACCEPTED,
            RunState.RUNNING,
            RunState.WAITING_FOR_CLARIFICATION,
            RunState.WAITING_FOR_BUDGET,
            RunState.REWORKING,
            RunState.CANCELLATION_REQUESTED,
            RunState.CANCELLED,
            RunState.FAILED,
            RunState.TIMED_OUT,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
}

TRANSITIONS = MappingProxyType(_TRANSITIONS)


class InvalidRunTransition(ValueError):
    def __init__(self, current: RunState, target: RunState) -> None:
        super().__init__(f"run cannot transition from {current.value} to {target.value}")
        self.current = current
        self.target = target


def ensure_transition(current: RunState, target: RunState) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidRunTransition(current, target)
