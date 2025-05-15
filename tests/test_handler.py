from datetime import datetime

import pytest

from src.outbox.handler import PydanticValidatedHandler, EventHandlerRouter
from src.outbox.schemas import BaseEventSchema


class DummySchema(BaseEventSchema):
    pass


class DummyHandler(PydanticValidatedHandler):
    model = DummySchema


class MockRecord:
    def __init__(self, *, id: int, queue: str, created_at: datetime, payload: dict):
        self.id = id
        self.queue = queue
        self.created_at = created_at
        self.payload = payload
        self.sent = False
        self.is_failed = False
        self.retry_count = 0


@pytest.fixture
def valid_record():
    return MockRecord(
        id=1,
        queue="dummy",
        created_at=datetime.now(),
        payload={"user_id": 123},
    )


@pytest.fixture
def invalid_record():
    return MockRecord(
        id=2,
        queue="dummy",
        created_at=datetime.now(),
        payload={},  # нет user_id
    )


def test_valid_payload(valid_record):
    handler = DummyHandler()
    payload = handler.to_payload(valid_record)
    assert payload["id"] == 1
    assert payload["user_id"] == 123


def test_invalid_payload(invalid_record):
    handler = DummyHandler()
    with pytest.raises(ValueError):
        handler.to_payload(invalid_record)


def test_router_dispatch(valid_record):
    handler = DummyHandler()
    router = EventHandlerRouter(handlers={"dummy": handler})
    result = router.to_payload(valid_record)
    assert result["id"] == valid_record.id


def test_router_default_handler(valid_record):
    default_handler = DummyHandler()
    router = EventHandlerRouter(handlers={}, default=default_handler)
    valid_record.queue = "unknown"
    result = router.to_payload(valid_record)
    assert result["id"] == valid_record.id


def test_router_no_handler(valid_record):
    router = EventHandlerRouter(handlers={})
    with pytest.raises(ValueError):
        router.to_payload(valid_record)
