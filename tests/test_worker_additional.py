import asyncio
import signal
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from faststream.rabbit import RabbitBroker

from src.outbox.handler import EventHandlerRouter
from src.outbox.protocols import EventRepositoryFactory, OutboxEventRepository
from src.outbox.worker import OutboxWorker


@asynccontextmanager
async def _dummy_repo() -> AsyncGenerator[OutboxEventRepository, None]:
    class DummyRepo(OutboxEventRepository):
        def __init__(self) -> None:
            class Session:
                async def commit(self) -> None:
                    pass

            self.session = Session()

        async def fetch_batch(self, _limit: int) -> list[Any]:
            return []

    yield DummyRepo()


dummy_repo_factory: EventRepositoryFactory = _dummy_repo


@pytest.mark.asyncio
async def test_run_polling_success(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AsyncMock(spec=RabbitBroker)
    broker.connect = AsyncMock()
    broker.close = AsyncMock()
    handler_router = MagicMock(spec=EventHandlerRouter)

    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=broker,
        handler_router=handler_router,
        batch_size=1,
        poll_interval=0.1,
    )

    stub_run = AsyncMock()
    monkeypatch.setattr(worker, "run_until_stop", stub_run)

    class DummyLoop:
        def __init__(self) -> None:
            self.handlers: list[tuple[signal.Signals, Callable[..., Any], tuple[object, ...]]] = []

        def add_signal_handler(self, sig: signal.Signals, cb: Callable[..., Any], *args: object) -> None:
            self.handlers.append((sig, cb, args))

    dummy_loop = DummyLoop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: dummy_loop)

    await worker.run_polling()

    regs = {sig for sig, _, _ in dummy_loop.handlers}
    assert regs == {signal.SIGINT, signal.SIGTERM}

    broker.connect.assert_awaited_once()
    stub_run.assert_awaited_once_with(dummy_loop)
    broker.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_polling_exception_still_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = AsyncMock(spec=RabbitBroker)
    broker.connect = AsyncMock()
    broker.close = AsyncMock()
    handler_router = MagicMock(spec=EventHandlerRouter)

    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=broker,
        handler_router=handler_router,
        batch_size=1,
        poll_interval=0.1,
    )

    stub_run = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(worker, "run_until_stop", stub_run)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: MagicMock())

    with pytest.raises(RuntimeError, match="boom"):
        await worker.run_polling()

    broker.connect.assert_awaited_once()
    stub_run.assert_awaited_once()
    broker.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_until_stop_one_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=AsyncMock(spec=RabbitBroker),
        handler_router=MagicMock(spec=EventHandlerRouter),
        batch_size=1,
        poll_interval=0.0,
        max_concurrent=1,
    )

    count = 0

    async def fake_batch() -> None:
        nonlocal count
        count += 1
        await worker.stop()

    monkeypatch.setattr(worker, "process_batch", fake_batch)

    loop = asyncio.get_running_loop()
    await worker.run_until_stop(loop)
    assert count == 1


@pytest.mark.asyncio
async def test_run_until_stop_covers_sleep_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    called_sleep = False
    count = 0

    class DummyLoop(asyncio.AbstractEventLoop):  # mypy: disable-error-code=abstract
        __abstractmethods__: ClassVar[set[str]] = set()

        def time(self) -> float:
            return 0.0

    loop = DummyLoop()  # type: ignore[abstract]

    orig_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        nonlocal called_sleep
        called_sleep = True
        await orig_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    worker = OutboxWorker(
        event_repository_factory=dummy_repo_factory,
        broker=AsyncMock(spec=RabbitBroker),
        handler_router=MagicMock(spec=EventHandlerRouter),
        batch_size=1,
        poll_interval=1.0,
        max_concurrent=1,
    )

    async def fake_batch() -> None:
        nonlocal count
        count += 1
        await worker.stop()

    monkeypatch.setattr(worker, "process_batch", fake_batch)

    await worker.run_until_stop(loop)
    assert count == 1
    assert called_sleep is True
