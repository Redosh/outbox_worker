from typing import TypeAlias
from .protocols import HasOutboxPayload

EventResults: TypeAlias = list[tuple[HasOutboxPayload, dict]]
