"""Single-number descriptive statistics only; no scoring or recommendations."""

if __package__:
    from .analysis_repository import ANALYSIS_START_DATE, AnalysisDraw, AnalysisSnapshot
else:
    from analysis_repository import ANALYSIS_START_DATE, AnalysisDraw, AnalysisSnapshot

TOTAL_NUMBERS = 49
MAIN_NUMBERS_PER_DRAW = 6
WINDOWS = (10, 30, 50, 100)


class InsufficientHistory(ValueError):
    def __init__(self, required, available):
        self.required, self.available = required, available
        super().__init__("insufficient analysis history")


def theoretical_probability(include_special=False):
    if type(include_special) is not bool:
        raise ValueError("include_special must be boolean")
    return (MAIN_NUMBERS_PER_DRAW + int(include_special)) / TOTAL_NUMBERS


def numbers_from_draw(draw: AnalysisDraw, include_special=False):
    theoretical_probability(include_special)
    return draw.numbers + ((draw.special_number,) if include_special else ())


def count_by_window(snapshot: AnalysisSnapshot, window: int, include_special=False):
    theoretical_probability(include_special)
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("window must be 10, 30, 50 or 100")
    if len(snapshot.draws) < window:
        raise InsufficientHistory(window, len(snapshot.draws))
    counts = {n: 0 for n in range(1, TOTAL_NUMBERS + 1)}
    for draw in snapshot.draws[-window:]:
        for number in numbers_from_draw(draw, include_special):
            counts[number] += 1
    return counts


def momentum_ratio(count: int, actual_draw_count: int, include_special=False):
    p = theoretical_probability(include_special)
    if type(count) is not int or type(actual_draw_count) is not int or not 0 <= count <= actual_draw_count or actual_draw_count <= 0:
        raise ValueError("require 0 <= count <= actual_draw_count and positive history")
    return count / (actual_draw_count * p)


def missing_count(snapshot: AnalysisSnapshot, number: int, include_special=False):
    theoretical_probability(include_special)
    if type(number) is not int or not 1 <= number <= TOTAL_NUMBERS:
        raise ValueError("number must be an integer in 1..49")
    if not snapshot.draws:
        raise InsufficientHistory(1, 0)
    for missing, draw in enumerate(reversed(snapshot.draws)):
        if number in numbers_from_draw(draw, include_special):
            return {"number": number, "missing_periods": missing, "is_lower_bound": False,
                    "last_draw": draw.draw, "last_date": draw.date.isoformat()}
    return {"number": number, "missing_periods": len(snapshot.draws), "is_lower_bound": True,
            "last_draw": None, "last_date": None}


def snapshot_metadata(snapshot, include_special, window, actual_draw_count):
    return {
        "analysis_start_date": ANALYSIS_START_DATE.isoformat(),
        "include_special": include_special,
        "theoretical_probability": theoretical_probability(include_special),
        "window": window,
        "actual_draw_count": actual_draw_count,
        "available_draw_count": len(snapshot.draws),
        "first_available_date": snapshot.draws[0].date.isoformat() if snapshot.draws else None,
        "latest_draw": snapshot.draws[-1].as_dict() if snapshot.draws else None,
        "cutoff_draw": snapshot.draws[-1].draw if snapshot.draws else None,
        "cutoff_date": snapshot.draws[-1].date.isoformat() if snapshot.draws else None,
    }


def draw_counts_response(snapshot, window=30, include_special=False):
    counts = count_by_window(snapshot, window, include_special)
    expected = window * theoretical_probability(include_special)
    return {**snapshot_metadata(snapshot, include_special, window, window),
            "numbers": [{"number": number, "count": count,
                         "theoretical_count": expected, "difference_from_average": count - expected,
                         "momentum_ratio": momentum_ratio(count, window, include_special)}
                        for number, count in counts.items()]}


def missing_numbers_response(snapshot, include_special=False):
    if not snapshot.draws:
        raise InsufficientHistory(1, 0)
    return {**snapshot_metadata(snapshot, include_special, None, len(snapshot.draws)),
            "history_scope": "available_analysis_draws",
            "note": "Counts observed draws only. Unseen numbers are lower bounds; archive completeness is not asserted.",
            "numbers": [missing_count(snapshot, number, include_special)
                        for number in range(1, TOTAL_NUMBERS + 1)]}
