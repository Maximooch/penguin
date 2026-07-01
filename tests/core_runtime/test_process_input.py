"""Tests for process input normalization helpers."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st

from penguin.core_runtime import process_input


def test_string_input_preserves_message_and_has_no_images_or_client_id() -> None:
    normalized = process_input.normalize_process_input("hello")

    assert normalized.message == "hello"
    assert normalized.image_paths is None
    assert normalized.client_message_id is None
    assert normalized.is_empty is False


def test_dict_input_preserves_text_and_nonblank_client_message_id() -> None:
    normalized = process_input.normalize_process_input(
        {"text": "hello", "client_message_id": " client_1 "}
    )

    assert normalized.message == "hello"
    assert normalized.client_message_id == " client_1 "


def test_blank_or_nonstring_client_message_id_is_filtered() -> None:
    assert (
        process_input.normalize_process_input(
            {"text": "hello", "client_message_id": "   "}
        ).client_message_id
        is None
    )
    assert (
        process_input.normalize_process_input(
            {"text": "hello", "client_message_id": 123}
        ).client_message_id
        is None
    )


def test_legacy_image_path_is_used_only_when_image_paths_is_empty() -> None:
    normalized = process_input.normalize_process_input(
        {"text": "see", "image_path": " /tmp/legacy.png "}
    )
    assert normalized.image_paths == ["/tmp/legacy.png"]

    whitespace_override = process_input.normalize_process_input(
        {
            "text": "see",
            "image_paths": "   ",
            "image_path": " /tmp/legacy.png ",
        }
    )
    assert whitespace_override.image_paths is None

    blank_list_override = process_input.normalize_process_input(
        {
            "text": "see",
            "image_paths": ["   "],
            "image_path": " /tmp/legacy.png ",
        }
    )
    assert blank_list_override.image_paths is None


def test_string_image_paths_is_wrapped_when_nonblank() -> None:
    normalized = process_input.normalize_process_input(
        {"text": "see", "image_paths": " /tmp/image.png "}
    )

    assert normalized.image_paths == ["/tmp/image.png"]


def test_list_image_paths_filters_to_nonblank_strings() -> None:
    normalized = process_input.normalize_process_input(
        {
            "text": "see",
            "image_paths": [
                " /tmp/one.png ",
                "",
                None,
                "   ",
                42,
                "/tmp/two.png",
            ],
        }
    )

    assert normalized.image_paths == ["/tmp/one.png", "/tmp/two.png"]


def test_empty_input_detection_matches_process_gate() -> None:
    assert process_input.normalize_process_input("").is_empty is True
    assert process_input.normalize_process_input({"text": ""}).is_empty is True
    assert (
        process_input.normalize_process_input(
            {"text": "", "image_paths": " /tmp/image.png "}
        ).is_empty
        is False
    )


@settings(max_examples=75)
@given(raw_paths=st.lists(st.one_of(st.text(), st.none(), st.integers())))
def test_list_image_paths_normalizes_to_stripped_nonblank_strings(
    raw_paths: list[Any],
) -> None:
    normalized = process_input.normalize_process_input(
        {"text": "see", "image_paths": raw_paths}
    )

    expected = [
        path.strip() for path in raw_paths if isinstance(path, str) and path.strip()
    ]
    assert normalized.image_paths == (expected or None)
    if normalized.image_paths is not None:
        assert all(isinstance(path, str) for path in normalized.image_paths)
        assert all(path == path.strip() for path in normalized.image_paths)
        assert all(path for path in normalized.image_paths)


@settings(max_examples=75)
@given(raw_path=st.text())
def test_string_image_paths_normalizes_to_single_stripped_path(
    raw_path: str,
) -> None:
    normalized = process_input.normalize_process_input(
        {"text": "see", "image_paths": raw_path}
    )

    assert normalized.image_paths == ([raw_path.strip()] if raw_path.strip() else None)
