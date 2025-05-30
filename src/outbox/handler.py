import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .protocols import HasOutboxPayload
from .schemas import BaseEventSchema

logger = logging.getLogger(__name__)

class EventHandler(ABC):
    queue_name: str

    @abstractmethod
    def to_payload(self, record: HasOutboxPayload) -> dict[str, Any]:
        ...


class PydanticValidatedHandler(EventHandler, ABC):
    model: type[BaseEventSchema]

    def to_payload(self, record: HasOutboxPayload) -> dict[str, Any]:
        logger.debug("Validating record id=%s queue=%s", record.id, record.queue)
        try:
            data = {
                **record.payload,
                "id": record.id,
                "created_at": record.created_at,
                "user_id": record.payload.get("user_id"),
            }
            obj = self.model(**data)
        except ValidationError as err:
            message = f"Invalid payload for event {record.id}: {err}"
            raise ValueError(message) from err
        return obj.model_dump()


_handler_registry: dict[str, EventHandler] = {}


def event_handler(queue_name: str) -> Callable[[type[EventHandler]], type[EventHandler]]:
    def decorator(cls: type[EventHandler]) -> type[EventHandler]:
        instance = cls()
        if queue_name in _handler_registry:
            msg = f"Handler for queue '{queue_name}' already registered"
            raise ValueError(msg)
        instance.queue_name = queue_name
        _handler_registry[queue_name] = instance
        logger.debug(
            "Registered handler %s for queue '%s'",
            cls.__name__, queue_name,
        )
        return cls

    return decorator


def get_registered_handlers() -> dict[str, EventHandler]:
    return dict(_handler_registry)


class EventHandlerRouter:
    def __init__(
        self,
        source: str,
        *,
        handlers: dict[str, EventHandler] | None = None,
        default: EventHandler | None = None,
    ) -> None:
        if not source:
            raise ValueError("Source should be set")
        self.source = source

        all_handlers = get_registered_handlers()
        if handlers:
            all_handlers.update(handlers)
        self._handlers = all_handlers
        self._default = default

    def get_handler(self, record: HasOutboxPayload) -> EventHandler:
        if record.queue in self._handlers:
            return self._handlers[record.queue]
        if self._default:
            return self._default
        msg = f"No handler for queue: '{record.queue}' {self._handlers}"
        raise ValueError(msg)

    def to_payload(self, record: HasOutboxPayload) -> dict[str, Any]:
        data = self.get_handler(record).to_payload(record)
        data["source"] = self.source
        return data
