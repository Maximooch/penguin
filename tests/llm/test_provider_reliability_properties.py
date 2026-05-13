from __future__ import annotations

from hypothesis import given, settings, strategies as st

from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMRequestLifecycle,
    ProviderRequestStatus,
)
from penguin.llm.runtime import should_retry_provider_failure
from penguin.tools.runtime import hash_tool_output, prepare_model_visible_tool_output


text_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=1000,
)


@given(output=text_strategy, max_chars=st.integers(min_value=1, max_value=200))
@settings(max_examples=100)
def test_tool_output_truncation_property_preserves_full_metadata(
    output: str,
    max_chars: int,
) -> None:
    view = prepare_model_visible_tool_output(output, max_chars=max_chars)

    assert view.full_output == output
    assert view.output_hash == hash_tool_output(output)
    assert view.byte_count == len(output.encode("utf-8"))
    assert view.line_count == (output.count("\n") + 1 if output else 0)
    assert len(view.model_output) <= max_chars
    assert view.truncated is (len(output) > max_chars)
    if not view.truncated:
        assert view.model_output == output


@given(
    retryable=st.booleans(),
    streamed_assistant_chunk=st.booleans(),
    pending_tool_call=st.booleans(),
    response=st.one_of(
        st.none(),
        st.sampled_from(["", "   ", "Error: synthetic", "[Error: synthetic]"]),
        text_strategy.filter(lambda value: not value.strip().startswith("Error:")),
    ),
)
@settings(max_examples=100)
def test_retry_policy_property_never_replays_unsafe_failures(
    retryable: bool,
    streamed_assistant_chunk: bool,
    pending_tool_call: bool,
    response: str | None,
) -> None:
    provider_error = LLMError(
        message="synthetic",
        category=ErrorCategory.NETWORK,
        retryable=retryable,
    )

    decision = should_retry_provider_failure(
        provider_error=provider_error,
        response=response,
        streamed_assistant_chunk=streamed_assistant_chunk,
        pending_tool_call=pending_tool_call,
    )

    assert decision is (
        retryable
        and not streamed_assistant_chunk
        and not pending_tool_call
        and (
            not response
            or not response.strip()
            or response.strip().startswith(("Error:", "[Error:"))
        )
    )


@given(
    status=st.sampled_from(list(ProviderRequestStatus)),
    finish_reason=st.one_of(st.none(), st.sampled_from(list(FinishReason))),
    error_category=st.one_of(st.none(), st.sampled_from(list(ErrorCategory))),
    retryable=st.booleans(),
)
@settings(max_examples=100)
def test_lifecycle_serialization_property_round_trips_canonical_fields(
    status: ProviderRequestStatus,
    finish_reason: FinishReason | None,
    error_category: ErrorCategory | None,
    retryable: bool,
) -> None:
    error = (
        LLMError(
            message="synthetic",
            category=error_category,
            retryable=retryable,
            provider="provider",
            model="model",
            finish_reason=finish_reason,
        )
        if error_category is not None
        else None
    )
    lifecycle = LLMRequestLifecycle(
        request_id="req-property",
        provider="provider",
        model="model",
        status=status,
        stream=True,
        transport="test",
        attempt=2,
        started_at=1.0,
        last_event_at=2.0,
        ended_at=3.0,
        provider_response_id="resp-property",
        last_event_type="event",
        finish_reason=finish_reason,
        error=error,
        provider_data={"key": "value"},
    )

    reloaded = LLMRequestLifecycle.from_dict(lifecycle.to_dict())

    assert reloaded.request_id == lifecycle.request_id
    assert reloaded.provider == lifecycle.provider
    assert reloaded.model == lifecycle.model
    assert reloaded.status == status
    assert reloaded.finish_reason == finish_reason
    assert reloaded.provider_data == lifecycle.provider_data
    if error is None:
        assert reloaded.error is None
    else:
        assert reloaded.error is not None
        assert reloaded.error.category == error_category
        assert reloaded.error.retryable is retryable
