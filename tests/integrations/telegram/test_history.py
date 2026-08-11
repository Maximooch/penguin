from penguin.integrations.telegram._history import GroupHistory


def test_group_history_bounds_lanes_messages_and_configured_slice() -> None:
    history = GroupHistory(max_lanes=2, max_messages=3)
    for value in ("one", "two", "three", "four"):
        history.append("lane-1", value)
    history.append("lane-2", "two")
    assert history.recent("lane-1", 2) == ["three", "four"]

    history.append("lane-3", "three")
    assert len(history) == 2
    assert history.recent("lane-2", 10) == []
    assert history.recent("lane-1", 10) == ["two", "three", "four"]
