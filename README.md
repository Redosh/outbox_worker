# outbox-worker

🌀 A generic asynchronous Outbox Worker for publishing events using FastStream and custom repositories. Supports payload validation and handler routing.

## Installation

```bash
pip install git+https://github.com/your-org/outbox-worker.git
```
Or add it to your pyproject.toml:
```toml
[dependencies]
outbox-worker = { git = "https://github.com/your-org/outbox-worker.git" }
```

## Quick Start
```python
from faststream.rabbit import RabbitBroker
from outbox_worker import OutboxWorker, EventHandlerRouter
from your_project.handlers import YourHandler
from your_project.repos import your_event_repository_factory

router = EventHandlerRouter(
    handlers={
        "queue_name": YourHandler(),
    }
)

worker = OutboxWorker(
    event_repository_factory=your_event_repository_factory,
    broker=RabbitBroker("amqp://localhost/"),
    handler_router=router,
    batch_size=100,
    poll_interval=1.0,
)

await worker.run_polling()
```

## Interfaces to Implement

### `HasOutboxPayload`: Your event record type. Must have the fields:

- `id: int`
- `queue: str`
- `created_at: datetime`
- `payload: dict`
- `sent: bool`
- `retry_count: int`
- `is_failed: bool`

### `OutboxEventRepository`: Repository that fetches batches of events.

- Method:  ```fetch_batch(limit: int) -> Sequence[HasOutboxPayload]```


- Property: ```.session.commit()``` must be an async method
### `EventHandler`: transforms a HasOutboxPayload record into a publishable dict
- Method: ```to_payload(record) -> dict```

### `EventHandlerRouter`: routes records to the appropriate handler by queue name.