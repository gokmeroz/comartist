"""Character identity and description."""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Character(BaseModel):
    """A character available for a comic chapter."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    description: str = ""
