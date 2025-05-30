from collections.abc import Generator

import pytest

from src.outbox import handler as handler_module
from src.outbox.handler import EventHandler, event_handler, get_registered_handlers


@pytest.fixture(autouse=True)
def clear_registry() -> Generator[None, None, None]:
    handler_module._handler_registry.clear()  # noqa: SLF001
    yield
    handler_module._handler_registry.clear()  # noqa: SLF001


def test_registry_starts_empty() -> None:
    assert get_registered_handlers() == {}


def test_event_handler_registration() -> None:
    @event_handler("foo")
    class FooHandler(EventHandler):
        def to_payload(self, _record: object) -> dict[str, bool]:
            return {"handled": True}

    regs = get_registered_handlers()
    assert "foo" in regs
    instance = regs["foo"]
    assert isinstance(instance, FooHandler)
    assert instance.queue_name == "foo"


def test_duplicate_registration_raises() -> None:
    @event_handler("bar")
    class BarHandler1(EventHandler):
        def to_payload(self, _record: object) -> dict[str, object]:
            return {}

    with pytest.raises(ValueError, match="Handler for queue 'bar' already registered"):
        @event_handler("bar")
        class BarHandler2(EventHandler):
            def to_payload(self, _record: object) -> dict[str, object]:
                return {}
