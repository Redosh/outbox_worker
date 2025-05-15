from abc import ABC, abstractmethod

from pydantic import ValidationError

from .protocols import HasOutboxPayload
from .schemas import BaseEventSchema


class EventHandler(ABC):
    @abstractmethod
    def to_payload(self, record: HasOutboxPayload) -> dict: ...


class PydanticValidatedHandler(EventHandler, ABC):
    model: type[BaseEventSchema]

    def to_payload(self, record: HasOutboxPayload) -> dict:
        try:
            data = {
                **record.payload,
                "id": record.id,
                "created_at": record.created_at,
                "user_id": record.payload.get("user_id"),
            }
            obj = self.model(**data)
        except ValidationError as err:
            raise ValueError(f"Invalid payload for event {record.id}: {err}")
        return obj.model_dump()


class EventHandlerRouter:
    def __init__(self, handlers: dict[str, EventHandler], default: EventHandler | None = None):
        self._handlers = handlers
        self._default = default

    def get_handler(self, record: HasOutboxPayload) -> EventHandler:
        if record.queue in self._handlers:
            return self._handlers[record.queue]
        if self._default:
            return self._default
        raise ValueError(f"No handler for queue: {record.queue}")

    def to_payload(self, record: HasOutboxPayload) -> dict:
        return self.get_handler(record).to_payload(record)
