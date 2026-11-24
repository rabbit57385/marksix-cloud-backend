"""Typed wire contract for the production foundation; no statistics model changes."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_engine import FORMULA_VERSION
from .analysis_repository import ANALYSIS_START_DATE, validate_cutoffs
from .models import Ball

SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "1.0.0"
FiniteNonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class AnalysisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0.0"]
    engine_version: Literal["1.0.0"]
    formula_version: str
    game: Literal["marksix"]
    include_special: bool
    theoretical_probability: Literal[6 / 49, 7 / 49]
    analysis_start_date: Literal["2020-01-01"]
    cutoff_draw: str
    cutoff_date: str
    previous_cutoff_draw: str
    previous_cutoff_date: str
    available_draw_count: Annotated[int, Field(ge=101, strict=True)]

    @field_validator("formula_version")
    @classmethod
    def known_formula(cls, value):
        if value != FORMULA_VERSION:
            raise ValueError("Unknown foundation formula")
        return value

    @model_validator(mode="after")
    def consistent_cutoffs(self):
        if self.theoretical_probability != (7 if self.include_special else 6) / 49:
            raise ValueError("Probability does not match analysis mode")
        for draw, value in ((self.cutoff_draw, self.cutoff_date),
                            (self.previous_cutoff_draw, self.previous_cutoff_date)):
            day = date.fromisoformat(value)
            if day.isoformat() != value or day < ANALYSIS_START_DATE:
                raise ValueError("Invalid cutoff date")
            validate_cutoffs(day, draw, True)
            if draw[:2] != str(day.year)[-2:]:
                raise ValueError("Cutoff draw year mismatch")
        if (self.previous_cutoff_date, self.previous_cutoff_draw) >= (self.cutoff_date, self.cutoff_draw):
            raise ValueError("Previous cutoff must precede current")
        return self


class AnalysisNumberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    number: Ball
    momentum: dict[Literal["10", "30", "50", "100"], FiniteNonnegative] = Field(min_length=4, max_length=4)
    score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    grade: Literal["A", "B", "C", "D", "E"]
    frozen_score: FiniteNonnegative
    momentum_type: str
    reasons: list[str]
    warnings: list[str]


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    metadata: AnalysisMetadata
    numbers: list[AnalysisNumberResponse] = Field(min_length=49, max_length=49)

    @field_validator("numbers")
    @classmethod
    def complete_ascending_numbers(cls, rows):
        if [r.number for r in rows] != list(range(1, 50)):
            raise ValueError("Require unique number-ascending 1..49")
        return rows
