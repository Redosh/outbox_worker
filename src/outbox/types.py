from typing import Any

from .protocols import HasOutboxPayload

type EventResults = list[tuple[HasOutboxPayload, dict[str, Any]]]
