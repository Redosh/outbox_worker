from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from faststream.rabbit import RabbitBroker

from src.outbox.handler import EventHandlerRouter, EventHandler
from src.outbox.worker import OutboxWorker


class MockRecord:
    def __init__(self, *, id: int, queue: str, created_at: datetime, payload: dict):
        self.id = id
        self.queue = queue
        self.created_at = created_at
        self.payload = payload
        self.sent = False
        self.is_failed = False
        self.retry_count = 0


class DummyHandler(EventHandler):
    def to_payload(self, record):
        return {
            "id": record.id,
            "created_at": record.created_at,
            "user_id": record.payload["user_id"]
        }


class DummyBroker:
    async def publish(self, payload: dict, queue: str):
        pass


class BrokenHandler(EventHandler):
    def to_payload(self, _):
        raise ValueError("fail")


class DummyOutboxEventRepo:
    async def fetch_batch(self, limit: int):
        return []

    @property
    def session(self):
        class DummySession:
            async def commit(self): pass

        return DummySession()


@asynccontextmanager
async def dummy_repo_factory() -> AsyncGenerator[DummyOutboxEventRepo, None]:
    yield DummyOutboxEventRepo()


# ===== Тесты =====

@pytest.mark.asyncio
async def test_prepare_tasks_info_valid():
    router = EventHandlerRouter({"q": DummyHandler()})
    dummy_broker = AsyncMock(spec=RabbitBroker)
    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=dummy_broker,
        handler_router=router,
        batch_size=1,
        poll_interval=1,
    )

    record = MockRecord(
        id=1,
        queue="q",
        created_at=datetime.now(),
        payload={"user_id": 1},
    )

    result = worker.prepare_tasks_info([record])
    assert len(result) == 1
    assert result[0][0].id == 1
    assert result[0][1]["user_id"] == 1


@pytest.mark.asyncio
async def test_prepare_tasks_info_invalid():
    router = EventHandlerRouter({"q": BrokenHandler()})
    dummy_broker = AsyncMock(spec=RabbitBroker)
    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=dummy_broker,
        handler_router=router,
        batch_size=1,
        poll_interval=1,
    )

    record = MockRecord(
        id=1,
        queue="q",
        created_at=datetime.now(),
        payload={"user_id": 1},
    )

    result = worker.prepare_tasks_info([record])
    assert len(result) == 0
    assert record.is_failed is True
