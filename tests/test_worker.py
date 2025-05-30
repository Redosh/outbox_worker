import asyncio
import types
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.outbox.protocols import HasOutboxPayload
from src.outbox.worker import MAX_RETRY_COUNT, OutboxWorker, count_complete_tasks


class DummyRecord:
    def __init__(self, rec_id: int = 1, queue: str = "q") -> None:
        self.id = rec_id
        self.queue = queue
        self.created_at: datetime = datetime.now(UTC)
        self.is_published: bool = False
        self.is_failed: bool = False
        self.retry_count: int = 0
        self.payload: dict[str, Any] = {}


@pytest.mark.parametrize(
    "retry_count, expected_queue",
    [
        (0, "q"),
        (MAX_RETRY_COUNT - 1, "q"),
        (MAX_RETRY_COUNT, "dead"),
        (MAX_RETRY_COUNT + 1, "dead"),
    ],
)
def test_resolve_queue(retry_count: int, expected_queue: str) -> None:
    record = DummyRecord(rec_id=42, queue="q")
    record.retry_count = retry_count
    worker = OutboxWorker(
        event_repository_factory=lambda: None,  # type: ignore[arg-type]
        broker=None,  # type: ignore[arg-type]
        handler_router=None,  # type: ignore[arg-type]
        batch_size=1,
        poll_interval=0.1,
        dead_letter_queue="dead",
    )
    assert worker._resolve_queue(record) == expected_queue  # noqa: SLF001


def test_count_complete_tasks() -> None:
    rec1 = DummyRecord()
    rec2 = DummyRecord()
    tasks_info: list[tuple[HasOutboxPayload, dict[str, Any]]] = [
        (rec1, {}),
        (rec2, {}),
    ]
    results: list[BaseException | None] = [None, Exception("fail")]
    sent = count_complete_tasks(tasks_info, results)
    assert sent == 1
    assert rec1.is_published is True
    assert rec1.retry_count == 0
    assert rec2.retry_count == 1
    assert rec2.is_published is False


@pytest.mark.asyncio
async def test_publish_events_and_payload() -> None:
    rec = DummyRecord()
    broker = MagicMock()

    async def fake_publish(payload: dict[str, Any], queue: str) -> None:
        if payload.get("id") == 2:
            raise RuntimeError("publish failed")

    broker.publish = AsyncMock(side_effect=fake_publish)

    worker = OutboxWorker(
        event_repository_factory=lambda: None,  # type: ignore[arg-type]
        broker=broker,
        handler_router=None,  # type: ignore[arg-type]
        batch_size=1,
        poll_interval=0.1,
    )

    tasks_info: list[tuple[HasOutboxPayload, dict[str, Any]]] = [
        (rec, {"id": 1}),
        (rec, {"id": 2}),
    ]
    results = await worker.publish_events(tasks_info)
    assert results[0] is None
    assert isinstance(results[1], RuntimeError)
    broker.publish.assert_any_await({"id": 1}, queue=rec.queue)
    broker.publish.assert_any_await({"id": 2}, queue=rec.queue)


def test_prepare_tasks_info() -> None:
    rec1 = DummyRecord(rec_id=1)
    rec2 = DummyRecord(rec_id=2)

    class FakeRouter:
        def to_payload(self, record: HasOutboxPayload) -> dict[str, Any]:
            if record.id == 1:
                return {"ok": True}
            raise ValueError("bad")

    worker = OutboxWorker(
        event_repository_factory=lambda: None,  # type: ignore[arg-type]
        broker=None,  # type: ignore[arg-type]
        handler_router=FakeRouter(),  # type: ignore[arg-type]
        batch_size=1,
        poll_interval=0.1,
    )

    tasks = worker.prepare_tasks_info([rec1, rec2])
    assert tasks == [(rec1, {"ok": True})]
    assert rec2.is_failed is True


@pytest.mark.asyncio
async def test_process_batch_empty() -> None:
    fake_session = types.SimpleNamespace(commit=AsyncMock())

    class FakeRepo:
        session = fake_session

        async def fetch_batch(self, _: int) -> list[HasOutboxPayload]:
            return []

    class FakeCM:
        async def __aenter__(self) -> FakeRepo:
            return FakeRepo()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            ...

    worker = OutboxWorker(
        event_repository_factory=lambda: FakeCM(),  # type: ignore[arg-type]
        broker=None,  # type: ignore[arg-type]
        handler_router=types.SimpleNamespace(),  # type: ignore[arg-type]
        batch_size=5,
        poll_interval=0.1,
    )
    worker.publish_events = AsyncMock(return_value=[])  # type: ignore[method-assign]
    await worker.process_batch()
    fake_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_batch_commits_on_non_empty() -> None:
    fake_session = types.SimpleNamespace(commit=AsyncMock())
    rec = DummyRecord(rec_id=99)

    class FakeRepo:
        session = fake_session

        async def fetch_batch(self, _: int) -> list[HasOutboxPayload]:
            return [rec]

    class FakeCM:
        async def __aenter__(self) -> FakeRepo:
            return FakeRepo()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            ...

    worker = OutboxWorker(
        event_repository_factory=lambda: FakeCM(),  # type: ignore[arg-type]
        broker=None,  # type: ignore[arg-type]
        handler_router=types.SimpleNamespace(),  # type: ignore[arg-type]
        batch_size=5,
        poll_interval=0.1,
    )
    worker.prepare_tasks_info = lambda _: [(rec, {"foo": "bar"})]  # type: ignore[assignment]
    worker.publish_events = AsyncMock(return_value=[None])  # type: ignore[method-assign]
    await worker.process_batch()
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """graceful-shutdown должен отменять все висящие задачи за один вызов stop()."""
    worker = OutboxWorker(
        event_repository_factory=lambda: None,  # type: ignore[arg-type]
        broker=None,                            # type: ignore[arg-type]
        handler_router=None,                    # type: ignore[arg-type]
        batch_size=1,
        poll_interval=0.1,
    )
    # ── подсовываем фиктивную «висящую» задачу ─────────────────────────
    class FakeTask:
        def __init__(self) -> None:
            self.cancel_called = False

        def cancel(self) -> None:
            self.cancel_called = True

    fake_task = FakeTask()
    worker._tasks.add(fake_task)  # type: ignore[arg-type]  # noqa: SLF001

    # ── заставляем asyncio.wait сразу вернуть её как pending ────────────
    async def fake_wait(
        tasks: set[asyncio.Task[Any]],
        timeout: float,  # noqa: ASYNC109
    ) -> tuple[set[asyncio.Task[Any]], set[asyncio.Task[Any]]]:
        return set(), tasks

    monkeypatch.setattr(asyncio, "wait", fake_wait)

    # ── вызываем graceful-shutdown один раз ─────────────────────────────
    await worker.stop()

    # ── убеждаемся, что задача была отменена ────────────────────────────
    assert fake_task.cancel_called is True
