from datetime import timedelta

from penguin.integrations.telegram.transport import classify_failure, retry_delay


class RetryAfter(Exception):
    def __init__(self) -> None:
        super().__init__("slow down")
        self.retry_after = timedelta(seconds=12)


class NetworkError(Exception):
    pass


class BadRequest(Exception):
    pass


class Conflict(Exception):
    pass


def test_classifies_retry_after_network_fatal_and_polling_conflict() -> None:
    assert classify_failure(RetryAfter()).retry_after == 12
    assert classify_failure(NetworkError()).retryable is True
    assert classify_failure(TimeoutError()).retryable is True
    assert classify_failure(BadRequest()).retryable is False
    assert classify_failure(Conflict()).polling_conflict is True


def test_retry_delay_is_bounded_and_honors_retry_after() -> None:
    assert retry_delay(3, base_seconds=2, max_seconds=30, random_value=lambda: 0) == 4
    assert retry_delay(10, base_seconds=2, max_seconds=30, random_value=lambda: 1) == 30
    assert retry_delay(1, base_seconds=2, max_seconds=30, retry_after=12) == 12
