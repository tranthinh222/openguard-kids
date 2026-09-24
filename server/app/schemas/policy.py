from typing import Any

from pydantic import BaseModel, Field

class PolicyResponse(BaseModel):
    id: str
    version: int
    payload: dict[str, Any]
    signature: str

    model_config = {"from_attributes": True}

