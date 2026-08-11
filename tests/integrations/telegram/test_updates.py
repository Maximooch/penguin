from penguin.integrations.telegram.updates import (
    envelope_from_dict,
    envelope_to_dict,
    is_addressed_to_bot,
    normalize_update,
    parse_command,
    strip_bot_mention,
)


def _message_update(**message_overrides):
    message = {
        "message_id": 5,
        "chat": {"id": -1001, "type": "supergroup", "title": "Penguins"},
        "from": {"id": 42, "username": "max"},
        "message_thread_id": 7,
        "text": "@Penguin_agent_bot hello",
    }
    message.update(message_overrides)
    return {"update_id": 99, "message": message}


def test_normalize_group_topic_and_round_trip() -> None:
    envelope = normalize_update(_message_update(), account_id="867")

    assert envelope is not None
    assert envelope.event_id == "telegram:867:99"
    assert envelope.address.chat_id == "-1001"
    assert envelope.address.topic_id == "7"
    assert envelope.sender_id == "42"
    assert envelope.metadata["chat_type"] == "supergroup"
    assert envelope_from_dict(envelope_to_dict(envelope)) == envelope


def test_photo_and_document_are_metadata_only() -> None:
    envelope = normalize_update(
        _message_update(
            text=None,
            caption="files",
            photo=[
                {"file_id": "small", "file_size": 10},
                {"file_id": "large", "file_size": 20},
            ],
            document={
                "file_id": "doc",
                "file_name": "notes.txt",
                "mime_type": "text/plain",
                "file_size": 30,
            },
        ),
        account_id="867",
    )

    assert envelope is not None
    assert [(item.kind, item.file_id) for item in envelope.attachments] == [
        ("photo", "large"),
        ("document", "doc"),
    ]
    assert "bytes" not in repr(envelope)


def test_callback_uses_callback_sender_and_message_scope() -> None:
    update = {
        "update_id": 100,
        "callback_query": {
            "id": "callback",
            "from": {"id": 55},
            "data": "penguin:abc:approve",
            "message": _message_update()["message"],
        },
    }
    envelope = normalize_update(update, account_id="867")

    assert envelope is not None
    assert envelope.sender_id == "55"
    assert envelope.metadata["callback_data"] == "penguin:abc:approve"


def test_empty_service_message_is_not_normalized() -> None:
    assert (
        normalize_update(
            _message_update(text=None, new_chat_members=[{"id": 99}]),
            account_id="867",
        )
        is None
    )


def test_senderless_group_migration_is_normalized() -> None:
    envelope = normalize_update(
        _message_update(text=None, **{"from": None}, migrate_from_chat_id=-1000),
        account_id="867",
    )

    assert envelope is not None
    assert envelope.sender_id == ""
    assert envelope.metadata["migrate_from_chat_id"] == "-1000"


def test_command_targeting_and_mention_stripping() -> None:
    assert parse_command("/status@Penguin_agent_bot now") == (
        "status",
        "now",
        "Penguin_agent_bot",
    )
    assert is_addressed_to_bot("/status@Penguin_agent_bot", "Penguin_agent_bot")
    assert not is_addressed_to_bot("/status@Other_bot", "Penguin_agent_bot")
    assert (
        strip_bot_mention("please @penguin_AGENT_bot help", "Penguin_agent_bot")
        == "please  help"
    )
