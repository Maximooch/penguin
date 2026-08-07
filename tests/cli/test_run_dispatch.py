"""Contract matrix for top-level CLI dispatch precedence."""

import pytest

from penguin.cli.run_dispatch import (
    DispatchMode,
    DispatchRequest,
    select_dispatch_mode,
)


@pytest.mark.parametrize(
    ("dispatch_request", "expected"),
    [
        (
            DispatchRequest("task", True, "session", "prompt", True, None),
            DispatchMode.RUN_MODE,
        ),
        (DispatchRequest(None, True, None, "prompt", True, None), DispatchMode.SESSION),
        (
            DispatchRequest(None, False, "session", "prompt", True, None),
            DispatchMode.SESSION,
        ),
        (
            DispatchRequest(None, False, None, "prompt", True, None),
            DispatchMode.DIRECT_PROMPT,
        ),
        (DispatchRequest(None, False, None, None, True, None), DispatchMode.CONTINUOUS),
        (
            DispatchRequest(None, False, None, None, False, None),
            DispatchMode.INTERACTIVE,
        ),
        (
            DispatchRequest(None, False, None, None, False, "project"),
            DispatchMode.SUBCOMMAND,
        ),
    ],
)
def test_dispatch_precedence(
    dispatch_request: DispatchRequest, expected: DispatchMode
) -> None:
    assert select_dispatch_mode(dispatch_request) is expected
