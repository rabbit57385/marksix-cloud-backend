"""Pure dual-mode analysis from a single already-loaded MarkSix history."""

from dataclasses import dataclass, field
from datetime import date

from .analysis_repository import AnalysisSnapshot
from .analysis_rules import (
    build_reasons, classify_grade, classify_momentum_type,
    frozen_long_hot_score, score_number,
)
from .statistics_core import (
    WINDOWS, InsufficientHistory, count_by_window, momentum_ratio,
    theoretical_probability,
)

FORMULA_VERSION = "marksix-v7-foundation-1"


@dataclass(frozen=True)
class AnalysisNumber:
    number: int
    r10: float
    r30: float
    r50: float
    r100: float
    score: float
    grade: str
    frozen_score: float
    momentum_type: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class NumberAnalysisSnapshot:
    cutoff_draw: str
    cutoff_date: date
    available_draw_count: int
    numbers: tuple[AnalysisNumber, ...]
    formula_version: str = field(default=FORMULA_VERSION, init=False)
    include_special: bool = False
    @property
    def theoretical_probability(self) -> float:
        return theoretical_probability(self.include_special)


@dataclass(frozen=True)
class AnalysisFoundation:
    current: NumberAnalysisSnapshot
    previous: NumberAnalysisSnapshot


def _analyze(history: AnalysisSnapshot, include_special: bool) -> NumberAnalysisSnapshot:
    counts = {w: count_by_window(history, w, include_special) for w in WINDOWS}
    rows = []
    for number in range(1, 50):
        ratios = tuple(momentum_ratio(counts[w][number], w, include_special) for w in WINDOWS)
        score, score_reasons, score_warnings = score_number(*ratios)
        extra_reasons, extra_warnings = build_reasons(*ratios)
        rows.append(AnalysisNumber(
            number, *ratios, score, classify_grade(score),
            frozen_long_hot_score(ratios[2], ratios[3]),
            classify_momentum_type(*ratios),
            tuple(dict.fromkeys(score_reasons + extra_reasons)),
            tuple(dict.fromkeys(score_warnings + extra_warnings)),
        ))
    latest = history.draws[-1]
    return NumberAnalysisSnapshot(latest.draw, latest.date, len(history.draws), tuple(rows), include_special)


def build_analysis_foundation(history: AnalysisSnapshot, include_special: bool = False) -> AnalysisFoundation:
    """No IO. Caller loads history once with its requested cutoff.

    Rows are number-ascending, not a V7/ranking-page ranking. Previous is rebuilt
    from the ordered prefix, never a draw-number guess or ratio subtraction.
    The input boundary/cutoff has already been validated by AnalysisSnapshot.
    """
    if not isinstance(history, AnalysisSnapshot):
        raise TypeError("history must be an AnalysisSnapshot")
    if len(history.draws) < 101:
        raise InsufficientHistory(101, len(history.draws))
    previous = AnalysisSnapshot(history.draws[:-1])
    return AnalysisFoundation(_analyze(history, include_special), _analyze(previous, include_special))
