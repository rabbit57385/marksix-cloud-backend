"""Analysis-only history boundary and immutable, chronologically ordered snapshots."""

import re
from dataclasses import dataclass
from datetime import date, datetime

from .database import SELECT_COLUMNS, connect_database, row_to_draw
from .models import validate_draw

ANALYSIS_START_DATE = date(2020, 1, 1)


class AnalysisDataError(ValueError):
    """Invalid stored history; never expose raw driver errors or records."""


class InvalidCutoff(ValueError):
    pass


def validate_cutoffs(cutoff_date, cutoff_draw, include_cutoff_draw):
    if cutoff_date is not None and (not isinstance(cutoff_date, date) or isinstance(cutoff_date, datetime)):
        raise InvalidCutoff("cutoff_date must be a calendar date")
    if cutoff_date is not None and cutoff_date < ANALYSIS_START_DATE:
        raise InvalidCutoff("cutoff_date precedes analysis start")
    if cutoff_draw is not None and (
        not isinstance(cutoff_draw, str)
        or not re.fullmatch(r"[0-9]{2}/[0-9]{3}", cutoff_draw)
        or cutoff_draw.endswith("/000")
    ):
        raise InvalidCutoff("cutoff_draw must use YY/NNN")
    if type(include_cutoff_draw) is not bool:
        raise InvalidCutoff("include_cutoff_draw must be boolean")
    if not include_cutoff_draw and cutoff_draw is None:
        raise InvalidCutoff("exclusive cutoff requires a cutoff_draw")


@dataclass(frozen=True)
class AnalysisDraw:
    draw: str
    date: date
    numbers: tuple[int, ...]
    special_number: int

    def __post_init__(self):
        if type(self.numbers) is not tuple or type(self.date) is not date:
            raise AnalysisDataError("draw must contain immutable numbers and a calendar date")
        validate_draw(self.as_dict())

    @classmethod
    def from_record(cls, value):
        item = validate_draw(value)
        return cls(item["draw"], date.fromisoformat(item["date"]),
                   tuple(item["numbers"]), item["special_number"])

    def as_dict(self):
        return {"draw": self.draw, "date": self.date.isoformat(),
                "numbers": list(self.numbers), "special_number": self.special_number}

    @property
    def sort_key(self):
        return self.date, self.draw


@dataclass(frozen=True)
class AnalysisSnapshot:
    # Always oldest -> newest; nested records are also immutable.
    draws: tuple[AnalysisDraw, ...]
    requested_cutoff_date: date | None = None
    requested_cutoff_draw: str | None = None
    include_cutoff_draw: bool = True

    def __post_init__(self):
        validate_cutoffs(self.requested_cutoff_date, self.requested_cutoff_draw, self.include_cutoff_draw)
        if type(self.draws) is not tuple or any(not isinstance(d, AnalysisDraw) for d in self.draws):
            raise AnalysisDataError("snapshot requires immutable draws")
        if any(d.date < ANALYSIS_START_DATE for d in self.draws):
            raise AnalysisDataError("pre-2020 data in analysis snapshot")
        if self.requested_cutoff_date and any(d.date > self.requested_cutoff_date for d in self.draws):
            raise AnalysisDataError("draw after cutoff date")
        if list(self.draws) != sorted(self.draws, key=lambda d: d.sort_key):
            raise AnalysisDataError("analysis snapshot must be oldest to newest")
        if len({d.draw for d in self.draws}) != len(self.draws):
            raise AnalysisDataError("duplicate draw in analysis snapshot")

    @classmethod
    def from_records(cls, records, *, cutoff_date=None, cutoff_draw=None, include_cutoff_draw=True):
        validate_cutoffs(cutoff_date, cutoff_draw, include_cutoff_draw)
        draws = [AnalysisDraw.from_record(value) for value in records]
        draws = sorted((d for d in draws if d.date >= ANALYSIS_START_DATE
                        and (cutoff_date is None or d.date <= cutoff_date)), key=lambda d: d.sort_key)
        if len({d.draw for d in draws}) != len(draws):
            raise AnalysisDataError("duplicate draw in analysis history")
        if cutoff_draw is not None:
            anchor = next((d for d in draws if d.draw == cutoff_draw), None)
            if anchor is None:
                raise InvalidCutoff("cutoff draw not found within analysis/date bounds")
            draws = [d for d in draws if d.sort_key <= anchor.sort_key
                     and (include_cutoff_draw or d.draw != cutoff_draw)]
        return cls(tuple(draws), cutoff_date, cutoff_draw, include_cutoff_draw)

    def newest_first(self):
        """Explicit display ordering; cannot reorder the engine's snapshot."""
        return tuple(reversed(self.draws))


class AnalysisRepository:
    def load_analysis_draws(self, *, cutoff_date=None, cutoff_draw=None,
                            include_cutoff_draw=True) -> AnalysisSnapshot:
        """One SELECT, no LIMIT. Date/draw bounds inclusive by default.

        For a prediction BEFORE a target draw, use cutoff_draw=target and
        include_cutoff_draw=False. The target's balls never enter the snapshot.
        Both bounds together are an intersection; missing anchors are errors.
        """
        validate_cutoffs(cutoff_date, cutoff_draw, include_cutoff_draw)
        clauses = ["draw_date >= %s"]
        params = [ANALYSIS_START_DATE]
        if cutoff_date is not None:
            clauses.append("draw_date <= %s")
            params.append(cutoff_date)
        if cutoff_draw is not None:
            # Anchor lookup and history read share a single SQL statement snapshot.
            # Include anchor for existence validation, then remove it if exclusive.
            clauses.append("(draw_date, draw) <= (SELECT draw_date, draw FROM marksix.draws "
                           "WHERE draw = %s AND draw_date >= %s)")
            params.extend((cutoff_draw, ANALYSIS_START_DATE))
        query = (f"SELECT {SELECT_COLUMNS} FROM marksix.draws WHERE "
                 + " AND ".join(clauses) + " ORDER BY draw_date ASC, draw ASC")
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                records = [row_to_draw(row) for row in cursor.fetchall()]
        # Defense in depth at the pure-engine boundary, including test overrides.
        return AnalysisSnapshot.from_records(records, cutoff_date=cutoff_date,
                                             cutoff_draw=cutoff_draw,
                                             include_cutoff_draw=include_cutoff_draw)
