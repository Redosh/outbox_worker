# outbox-worker

A generic asynchronous Outbox Worker for publishing events using FastStream (RabbitMQ) and custom repositories. Supports payload validation, handler routing, retry policies, and dead-letter queues.

## Installation

Install from PyPI:

```bash
pip install outbox-worker
```

Or install the latest development version from GitHub:

```bash
pip install git+https://github.com/Redosh/outbox_worker.git
```

Or add to your `pyproject.toml`:

```toml
[tool.poetry.dependencies]
outbox-worker = "^0.1.0"
```

## Quick Start

```python
import asyncio
from faststream.rabbit import RabbitBroker
from outbox_worker import OutboxWorker, EventHandlerRouter

# Define your event schema
from src.outbox.schemas import BaseEventSchema
class UserCreatedSchema(BaseEventSchema):
    user_name: str

# Create a handler via decorator
from outbox_worker import event_handler, PydanticValidatedHandler
@event_handler("user_events")
class UserCreatedHandler(PydanticValidatedHandler):
    model = UserCreatedSchema

async def main():
    # Build handler router (handlers registered via decorator are auto-discovered)
    router = EventHandlerRouter(source="profile_service")

    # Configure broker
    broker = RabbitBroker("amqp://guest:guest@localhost/")

    # Instantiate worker
    worker = OutboxWorker(
        event_repository_factory=your_event_repository_factory,
        broker=broker,
        handler_router=router,
        batch_size=100,
        poll_interval=1.0,  # seconds between polls
        max_concurrent=5,
        dead_letter_queue="dead_letter",
    )

    await worker.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
```

## Decorator Usage

Use the `@event_handler(queue_name)` decorator to register handlers without manually populating the router:

```python
from outbox_worker import event_handler, PydanticValidatedHandler
from src.outbox.schemas import BaseEventSchema

class OrderShippedSchema(BaseEventSchema):
    order_id: int
    shipped_at: datetime

@event_handler("order_events")
class OrderShippedHandler(PydanticValidatedHandler):
    model = OrderShippedSchema
    
    async def handle(self, payload: dict[str, Any]) -> None:
        # process the shipped event
        ...
```

Handlers decorated this way are automatically registered in the global registry and picked up by `EventHandlerRouter`.

## Configuration Options

* **batch\_size** (`int`): Number of records fetched per batch.
* **poll\_interval** (`float`): Delay in seconds between batch polls.
* **max\_concurrent** (`int`, default 5): Maximum number of concurrent batch workers.
* **dead\_letter\_queue** (`str`, default "dead\_letter"): Queue name for messages that exceed retry limit.

## Core Interfaces

### `HasOutboxPayload`

Your record type must expose:

* `id: int`
* `queue: str`
* `created_at: datetime`
* `payload: dict[str, Any]`
* `is_published: bool`
* `retry_count: int`
* `is_failed: bool`

### `OutboxEventRepository`

```python
class MyRepo:
    async def fetch_batch(self, limit: int) -> Sequence[HasOutboxPayload]:
        ...
    async def mark_published(self, record: HasOutboxPayload) -> None: ...
    async def mark_failed(self, record: HasOutboxPayload) -> None: ...
```

### `EventHandlerRouter`

Routes by `record.queue`, with optional `default` handler.

## Contributing

1. Fork the repo
2. Create a feature branch
3. Open a PR against `main`

## License

MIT
