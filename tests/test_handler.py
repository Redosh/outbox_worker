from datetime import UTC, datetime
from typing import Any

import pytest

from src.outbox.handler import EventHandlerRouter, PydanticValidatedHandler
from src.outbox.schemas import BaseEventSchema


class DummySchema(BaseEventSchema):
    pass


class DummyHandler(PydanticValidatedHandler):
    model = DummySchema


class MockRecord:
    def __init__(
        self, *, event_id: int, queue: str, created_at: datetime, payload: dict[str, Any],
    ) -> None:
        self.id = event_id
        self.queue = queue
        self.created_at = created_at
        self.payload = payload
        self.is_published = False
        self.is_failed = False
        self.retry_count = 0


@pytest.fixture
def valid_record() -> MockRecord:
    return MockRecord(
        event_id=1,
        queue="dummy",
        created_at=datetime.now(UTC),
        payload={"user_id": 123},
    )


@pytest.fixture
def invalid_record() -> MockRecord:
    return MockRecord(
        event_id=2,
        queue="dummy",
        created_at=datetime.now(UTC),
        payload={},
    )


def test_valid_payload(valid_record: MockRecord) -> None:
    handler = DummyHandler()
    payload = handler.to_payload(valid_record)
    assert payload["id"] == valid_record.id
    assert payload["user_id"] == 123


def test_invalid_payload(invalid_record: MockRecord) -> None:
    handler = DummyHandler()
    with pytest.raises(ValueError, match=r"Invalid payload for event"):
        handler.to_payload(invalid_record)


def test_router_dispatch(valid_record: MockRecord) -> None:
    handler = DummyHandler()
    router = EventHandlerRouter(handlers={"dummy": handler}, source="test_source")
    result = router.to_payload(valid_record)
    assert result["id"] == valid_record.id
    assert result["user_id"] == valid_record.payload["user_id"]
    assert result["source"] == "test_source"


def test_router_default_handler(valid_record: MockRecord) -> None:
    default_handler = DummyHandler()
    router = EventHandlerRouter(handlers={}, source="test_source", default=default_handler)
    valid_record.queue = "unknown"
    result = router.to_payload(valid_record)
    assert result["id"] == valid_record.id
    assert result["source"] == "test_source"


def test_router_no_handler(valid_record: MockRecord) -> None:
    router = EventHandlerRouter(handlers={}, source="test_source")
    with pytest.raises(ValueError, match="No handler for queue"):
        router.to_payload(valid_record)


def test_router_init_without_source_raises() -> None:
    with pytest.raises(ValueError, match="Source should be set"):
        EventHandlerRouter(handlers={"dummy": DummyHandler()}, source="")
