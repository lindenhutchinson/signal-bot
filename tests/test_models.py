from signal_chatbot.transport.models import IncomingMessage

# The raw id signal-cli delivers in a receive envelope, and the matching
# internal id the REST bridge's /v1/groups and /v2/send expect.
RAW_GROUP_ID = "RXhhbXBsZVRlc3RHcm91cC0tbm90LWEtcmVhbC1zaWduYWwtaWQtLTAx"
INTERNAL_GROUP_ID = "group.UlhoaGJYQnNaVlJsYzNSSGNtOTFjQzB0Ym05MExXRXRjbVZoYkMxemFXZHVZV3d0YVdRdExUQXg="


def _group_text_envelope(text: str = "@bot hi") -> dict:
    return {
        "source": "+61400000001",
        "sourceName": "Alice",
        "timestamp": 1,
        "dataMessage": {
            "message": text,
            "timestamp": 1,
            "groupInfo": {"groupId": RAW_GROUP_ID},
        },
    }


def test_normalises_raw_group_id_to_internal_id() -> None:
    message = IncomingMessage.from_envelope(_group_text_envelope())

    assert message is not None
    # The raw signal-cli id must be converted to the bridge's internal form so
    # it matches the allowlist and is accepted as a send recipient.
    assert message.group_id == INTERNAL_GROUP_ID


def test_parses_sender_and_text() -> None:
    message = IncomingMessage.from_envelope(_group_text_envelope("hello there"))

    assert message is not None
    assert message.sender_number == "+61400000001"
    assert message.sender_name == "Alice"
    assert message.text == "hello there"


def test_ignores_non_group_message() -> None:
    envelope = {"dataMessage": {"message": "hi", "timestamp": 1}}  # no groupInfo

    assert IncomingMessage.from_envelope(envelope) is None


def test_ignores_non_data_message() -> None:
    envelope = {"receiptMessage": {"when": 1}}

    assert IncomingMessage.from_envelope(envelope) is None
