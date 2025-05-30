import asyncio
import logging
import signal
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from faststream.rabbit import RabbitBroker

from src.outbox.handler import (
    EventHandlerRouter,
    PydanticValidatedHandler,
    event_handler,
)
from src.outbox.protocols import HasOutboxPayload, OutboxEventRepository
from src.outbox.schemas import BaseEventSchema
from src.outbox.worker import OutboxWorker


def setup_logging() -> None:
    logging.basicConfig(
        level="DEBUG",
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


setup_logging()
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("aio_pika").setLevel(logging.INFO)
logging.getLogger("aiormq").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


class UserCreatedSchema(BaseEventSchema):
    user_name: str


@event_handler("user_events")
class UserCreatedHandler(PydanticValidatedHandler):
    model = UserCreatedSchema


@dataclass
class OutboxRecord(HasOutboxPayload):
    id: int
    queue: str
    created_at: datetime
    payload: dict[str, Any]

    is_published: bool = False
    is_failed: bool = False
    retry_count: int = 0


class InMemoryOutboxRepo(OutboxEventRepository):
    def __init__(self, storage: list[OutboxRecord]) -> None:
        self._storage = storage

        class _Sess:
            async def commit(self) -> None: ...

        self.session = _Sess()

    async def fetch_batch(self, limit: int) -> Sequence[OutboxRecord]:
        batch, self._storage[:] = self._storage[:limit], self._storage[limit:]
        return batch


class EventRepositoryFactory:
    def __init__(self, storage: list[OutboxRecord]) -> None:
        self.storage = storage

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[InMemoryOutboxRepo]:
        yield InMemoryOutboxRepo(self.storage)


async def main() -> None:
    broker = RabbitBroker("amqp://guest:guest@localhost/")
    router = EventHandlerRouter(source="auth_service")

    storage: list[OutboxRecord] = [
        OutboxRecord(
            id=1,
            queue="user_events",
            created_at=datetime.now(UTC),
            payload={"user_id": 42, "user_name": "Neo"},
        ),
    ]

    worker = OutboxWorker(
        event_repository_factory=EventRepositoryFactory(storage),
        broker=broker,
        handler_router=router,
        batch_size=10,
        poll_interval=1.0,
    )

    await worker.run_polling()


if __name__ == "__main__":
    if hasattr(signal, "SIGTERM"):
        asyncio.run(main())
    else:
        logger.info("SIGTERM not available on this platform")
