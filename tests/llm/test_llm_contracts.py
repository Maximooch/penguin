from __future__ import annotations

from penguin.llm.contracts import LLMUsage


def test_llm_usage_from_dict_derives_total_tokens_when_missing() -> None:
    usage = LLMUsage.from_dict(
        {
            "input_tokens": 12,
            "output_tokens": 7,
            "reasoning_tokens": 3,
        }
    )

    assert usage.input_tokens == 12
    assert usage.output_tokens == 7
    assert usage.reasoning_tokens == 3
    assert usage.total_tokens == 22
    assert usage.to_dict()["total_tokens"] == 22
