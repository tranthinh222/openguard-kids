from pydantic import BaseModel, Field

class ChildCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    birth_year: int | None = Field(default=None, ge=2000, le=2100)

class ChildResponse(BaseModel):
    id: str
    parent_id: str
    display_name: str
    birth_year: int | None

    model_config = {"from_attributes": True}

class ChildSummaryResponse(ChildResponse):
    device_count: int
    online_count: int