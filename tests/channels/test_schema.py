from penguin.channels.schema import ChannelAddress


def test_lane_key_distinguishes_topics_and_avoids_delimiter_collisions() -> None:
    topic_one = ChannelAddress("telegram", "bot", "chat", "1")
    topic_two = ChannelAddress("telegram", "bot", "chat", "2")
    ambiguous = ChannelAddress("telegram", "bot\x1fchat", "1", "")

    assert topic_one.lane_key != topic_two.lane_key
    assert topic_one.lane_key != ambiguous.lane_key
