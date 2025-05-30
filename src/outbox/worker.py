import asyncio
import logging
import signal
from collections.abc import Sequence
from typing import Any

from faststream.rabbit import RabbitBroker

from .handler import EventHandlerRouter
from .protocols import EventRepositoryFactory, HasOutboxPayload
from .types import EventResults

logger = logging.getLogger(__name__)

MAX_RETRY_COUNT = 5


class OutboxWorker:
    def __init__(  # noqa: PLR0913
        self,
        event_repository_factory: EventRepositoryFactory,
        broker: RabbitBroker,
        handler_router: EventHandlerRouter,
        batch_size: int,
        poll_interval: float,
        max_concurrent: int = 5,
        dead_letter_queue: str = "dead_letter",
    ) -> None:
        self.batch_size = batch_size
        self._poll_interval = poll_interval
        self._max_concurrent = max_concurrent

        self.broker = broker
        self.event_repository_factory = event_repository_factory
        self.handler_router = handler_router
        self.dead_letter_queue = dead_letter_queue

        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task[Any]] = set()

    async def run_polling(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # noinspection PyTypeChecker
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            logger.info("Connecting to broker…")
            await self.broker.connect()
            logger.info("Starting loop…")
            await self.run_until_stop(loop)
        finally:
            await self.broker.close()

    async def run_until_stop(self, loop: asyncio.AbstractEventLoop) -> None:
        semaphore = asyncio.Semaphore(self._max_concurrent)
        next_run = loop.time()

        async def _batch_worker() -> None:
            try:
                await self.process_batch()
            finally:
                semaphore.release()

        while not self._stop_event.is_set():
            await semaphore.acquire()
            task: asyncio.Task[Any] = asyncio.create_task(_batch_worker())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

            next_run += self._poll_interval
            sleep_for = next_run - loop.time()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    async def stop(self) -> None:
        if self._stop_event.is_set():
            return

        logger.info("Stopping OutboxWorker…")
        self._stop_event.set()

        current = asyncio.current_task()
        if current is not None:
            self._tasks.discard(current)

        while self._tasks:
            done, pending = await asyncio.wait(self._tasks, timeout=2)
            logger.debug("done=%d pending=%d", len(done), len(pending))

            for task in pending:
                logger.warning("Cancelling pending task %s", task)
                task.cancel()

            self._tasks.difference_update(done | pending)

        logger.info("OutboxWorker stopped")

    async def process_batch(self) -> None:
        async with self.event_repository_factory() as repo:
            records = await repo.fetch_batch(self.batch_size)
            if not records:
                logger.debug("No records fetched")
                return

            logger.debug("Fetched %d records", len(records))
            tasks_info = self.prepare_tasks_info(records)
            results = await self.publish_events(tasks_info)
            sent = count_complete_tasks(tasks_info, results)

            await repo.session.commit()

        fetched = len(records)
        invalid = fetched - len(tasks_info)
        failed_publish = len(results) - sent
        logger.info(
            "Batch stats: fetched=%d invalid=%d sent=%d failed=%d",
            fetched,
            invalid,
            sent,
            failed_publish,
        )

    def prepare_tasks_info(self, records: Sequence[HasOutboxPayload]) -> EventResults:
        tasks_info: EventResults = []
        for record in records:
            # noinspection PyBroadException
            try:
                payload = self.handler_router.to_payload(record)
            except Exception:
                logger.exception("Failed parse payload")
                record.is_failed = True
                continue
            tasks_info.append((record, payload))
        return tasks_info

    async def publish_events(
        self,
        tasks_info: EventResults,
    ) -> list[BaseException | None]:
        tasks = [
            asyncio.create_task(self.publish_event_payload(record, payload))
            for record, payload in tasks_info
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def publish_event_payload(
        self,
        record: HasOutboxPayload,
        payload: dict[str, Any],
    ) -> None:
        # noinspection PyBroadException
        try:
            queue = self._resolve_queue(record)
            await self.broker.publish(payload, queue=queue)
        except Exception:
            logger.exception("Failed to publish id=%s", payload.get("id"))
            raise

    def _resolve_queue(self, record: HasOutboxPayload) -> str:
        if record.retry_count >= MAX_RETRY_COUNT:
            return self.dead_letter_queue
        return record.queue


def count_complete_tasks(
    tasks_info: EventResults,
    results: list[BaseException | None],
) -> int:
    sent = 0
    for (record, _), result in zip(tasks_info, results, strict=False):
        if isinstance(result, Exception):
            record.retry_count += 1
        else:
            record.is_published = True
            sent += 1
    return sent
