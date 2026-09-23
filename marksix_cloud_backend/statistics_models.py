"""Contracts for descriptive statistics, separate from raw draw responses."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Ball, Draw

NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]


class SnapshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_start_date: Literal["2020-01-01"]
    include_special: bool
    theoretical_probability: float
    window: Literal[10, 30, 50, 100] | None
    actual_draw_count: NonnegativeInt
    available_draw_count: NonnegativeInt
    first_available_date: str | None
    latest_draw: Draw | None
    cutoff_draw: str | None
    cutoff_date: str | None


class NumberCount(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    number: Ball
    count: NonnegativeInt
    theoretical_count: float
    difference_from_average: float
    momentum_ratio: float


class DrawCountsResponse(SnapshotMetadata):
    window: Literal[10, 30, 50, 100]
    numbers: list[NumberCount] = Field(min_length=49, max_length=49)


class MissingNumber(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    number: Ball
    missing_periods: NonnegativeInt
    is_lower_bound: bool
    last_draw: str | None
    last_date: str | None


class MissingNumbersResponse(SnapshotMetadata):
    window: None
    history_scope: Literal["available_analysis_draws"]
    note: str
    numbers: list[MissingNumber] = Field(min_length=49, max_length=49)


class OverviewResponse(BaseModel):
    """Homepage statistics share one analysis snapshot; primary mains only."""

    model_config = ConfigDict(extra="forbid", strict=True)
    latest: Draw
    recent_draws: list[Draw] = Field(min_length=20, max_length=20)
    momentum: dict[Literal["10", "30", "50", "100"], DrawCountsResponse] = Field(
        min_length=4, max_length=4
    )
    missing: MissingNumbersResponse
    analysis: SnapshotMetadata
