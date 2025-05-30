from datetime import datetime

from pydantic import BaseModel, NonNegativeInt


class BaseEventSchema(BaseModel):
    id: NonNegativeInt
    created_at: datetime
    user_id: NonNegativeInt
