from datetime import datetime
from typing import Protocol, Sequence, AsyncContextManager


class HasOutboxPayload(Protocol):
    id: int
    queue: str

    created_at: datetime
    is_published: bool
    is_failed: bool
    retry_count: int

    payload: dict


class HasCommit(Protocol):
    async def commit(self) -> None: ...


class OutboxEventRepository(Protocol):
    session: HasCommit

    async def fetch_batch(self, limit: int) -> Sequence[HasOutboxPayload]:
        ...


class EventRepositoryFactory(Protocol):
    def __call__(self) -> AsyncContextManager[OutboxEventRepository]:
        ...
