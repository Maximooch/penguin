from __future__ import annotations

from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMRequestLifecycle,
    ProviderRequestStatus,
)


TERMINAL_STATUSES = {
    ProviderRequestStatus.COMPLETED,
    ProviderRequestStatus.DISCONNECTED,
    ProviderRequestStatus.FAILED,
    ProviderRequestStatus.CANCELLED,
}


@settings(max_examples=25, stateful_step_count=20)
class LifecycleSerializationMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.lifecycle = LLMRequestLifecycle(
            request_id="req-state-machine",
            provider="provider",
            model="model",
            status=ProviderRequestStatus.PENDING,
            stream=True,
            transport="test",
            started_at=1.0,
            last_event_at=1.0,
        )

    @initialize()
    def initialize_lifecycle(self) -> None:
        self.lifecycle = LLMRequestLifecycle(
            request_id="req-state-machine",
            provider="provider",
            model="model",
            status=ProviderRequestStatus.PENDING,
            stream=True,
            transport="test",
            started_at=1.0,
            last_event_at=1.0,
        )

    @rule(status=st.sampled_from(list(ProviderRequestStatus)))
    def update_status(self, status: ProviderRequestStatus) -> None:
        self.lifecycle.status = status
        self.lifecycle.last_event_at += 1.0
        if status in TERMINAL_STATUSES:
            self.lifecycle.ended_at = self.lifecycle.last_event_at
        else:
            self.lifecycle.ended_at = None

    @rule(finish_reason=st.sampled_from(list(FinishReason)))
    def update_finish_reason(self, finish_reason: FinishReason) -> None:
        self.lifecycle.finish_reason = finish_reason
        self.lifecycle.last_event_type = f"finish:{finish_reason.value}"

    @rule(category=st.sampled_from(list(ErrorCategory)), retryable=st.booleans())
    def record_error(self, category: ErrorCategory, retryable: bool) -> None:
        self.lifecycle.error = LLMError(
            message=f"{category.value} error",
            category=category,
            retryable=retryable,
            provider=self.lifecycle.provider,
            model=self.lifecycle.model,
        )
        self.lifecycle.status = (
            ProviderRequestStatus.DISCONNECTED
            if category in {ErrorCategory.NETWORK, ErrorCategory.TIMEOUT}
            else ProviderRequestStatus.FAILED
        )
        self.lifecycle.last_event_at += 1.0
        self.lifecycle.ended_at = self.lifecycle.last_event_at

    @rule()
    def round_trip_through_storage_record(self) -> None:
        reloaded = LLMRequestLifecycle.from_dict(self.lifecycle.to_dict())

        assert reloaded.request_id == self.lifecycle.request_id
        assert reloaded.provider == self.lifecycle.provider
        assert reloaded.model == self.lifecycle.model
        assert reloaded.status == self.lifecycle.status
        assert reloaded.finish_reason == self.lifecycle.finish_reason
        assert reloaded.ended_at == self.lifecycle.ended_at
        if self.lifecycle.error is None:
            assert reloaded.error is None
        else:
            assert reloaded.error is not None
            assert reloaded.error.category == self.lifecycle.error.category
            assert reloaded.error.retryable == self.lifecycle.error.retryable

        self.lifecycle = reloaded

    @invariant()
    def terminal_statuses_have_end_timestamp(self) -> None:
        if self.lifecycle.status in TERMINAL_STATUSES:
            assert self.lifecycle.ended_at is not None


TestLifecycleSerialization = LifecycleSerializationMachine.TestCase
