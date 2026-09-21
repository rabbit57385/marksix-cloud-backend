"""Shared validation for HKJC, database writes, and public API responses."""

from datetime import date as Date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Ball = Annotated[int, Field(strict=True, ge=1, le=49)]


class Draw(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    draw: str = Field(pattern=r"^[0-9]{2}/[0-9]{3}$")
    date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    numbers: list[Ball] = Field(min_length=6, max_length=6)
    special_number: Ball

    @field_validator("draw")
    @classmethod
    def nonzero_draw(cls, value: str) -> str:
        if value.endswith("/000"):
            raise ValueError("draw sequence must be positive")
        return value

    @field_validator("date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        Date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def integrity(self) -> "Draw":
        if len(set(self.numbers)) != 6:
            raise ValueError("six main numbers must be distinct")
        if self.special_number in self.numbers:
            raise ValueError("special_number must not occur in numbers")
        if self.date[2:4] != self.draw[:2]:
            raise ValueError("draw year must match date year")
        return self


class RecentDraws(BaseModel):
    draws: list[Draw]


def validate_draw(value: object) -> dict:
    """Reject coercions (including bool/float balls), preserve official order."""
    return Draw.model_validate(value).model_dump()
