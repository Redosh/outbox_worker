import asyncio
import logging
from typing import Sequence

from faststream.rabbit import RabbitBroker

from .handler import EventHandlerRouter
from .protocols import (
    EventRepositoryFactory,
    HasOutboxPayload,
)
from .types import EventResults

logger = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(
        self,
        event_repository_factory: EventRepositoryFactory,
        broker: RabbitBroker,
        handler_router: EventHandlerRouter,
        batch_size: int,
        poll_interval: float,
        max_concurrent: int = 5,
        dead_letter_queue: str = "dead_letter"
    ):
        self.batch_size = batch_size
        self._poll_interval = poll_interval
        self._max_concurrent = max_concurrent

        self.broker = broker
        self.event_repository_factory = event_repository_factory
        self.handler_router = handler_router
        self.dead_letter_queue = dead_letter_queue

        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def run_polling(self) -> None:
        loop = asyncio.get_running_loop()
        semaphore = asyncio.Semaphore(self._max_concurrent)
        next_run = loop.time()

        async def _batch_worker():
            try:
                await self.process_batch()
            finally:
                semaphore.release()

        while not self._stop_event.is_set():
            await semaphore.acquire()
            task = asyncio.create_task(_batch_worker())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

            next_run += self._poll_interval
            sleep_for = next_run - loop.time()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    async def stop(self) -> None:
        self._stop_event.set()
        if not self._tasks:
            return
        done, pending = await asyncio.wait(self._tasks, timeout=2)
        for task in pending:
            task.cancel()

    async def process_batch(self) -> None:
        async with self.event_repository_factory() as repo:
            records = await repo.fetch_batch(self.batch_size)
            if not records:
                return

            tasks_info = self.prepare_tasks_info(records)
            results = await self.publish_events(tasks_info)
            sent = count_complete_tasks(tasks_info, results)

            await repo.session.commit()

        fetched = len(records)
        invalid = fetched - len(tasks_info)
        failed_publish = len(results) - sent
        logger.info(
            "fetched=%d, invalid=%d, sent=%d, publish_failures=%d",
            fetched, invalid, sent, failed_publish,
        )

    def prepare_tasks_info(
        self,
        records: Sequence[HasOutboxPayload],
    ) -> EventResults:
        tasks_info: EventResults = []
        for record in records:
            try:
                payload = self.handler_router.to_payload(record)
            except Exception as err:
                logger.warning("Invalid payload id=%s: %s", record.id, err)
                record.is_failed = True
                continue
            tasks_info.append((record, payload))
        return tasks_info

    async def publish_events(self, tasks_info: EventResults):
        tasks = [
            asyncio.create_task(self.publish_event_payload(record, payload))
            for record, payload in tasks_info
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def publish_event_payload(self, record: HasOutboxPayload, payload: dict) -> None:
        try:
            queue = self._resolve_queue(record)
            await self.broker.publish(payload, queue=queue)
        except Exception as err:
            logger.error("Failed to publish id=%s: %s", payload.get("id"), err)
            raise

    def _resolve_queue(self, record: HasOutboxPayload) -> str:
        if record.retry_count >= 5:
            return self.dead_letter_queue
        return record.queue


def count_complete_tasks(tasks_info: EventResults, results: list[None | Exception]) -> int:
    sent = 0
    for (record, _), result in zip(tasks_info, results):
        if isinstance(result, Exception):
            record.retry_count += 1
        else:
            record.is_published = True
            sent += 1
    return sent
