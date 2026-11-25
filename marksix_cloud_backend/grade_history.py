"""MarkSix pre-draw grade history from the existing V7 analysis foundation."""
from .analysis_engine import _analyze
from .analysis_repository import AnalysisSnapshot
from .analysis_models import ENGINE_VERSION
from .draw_sync import source_revision, api_draw
from .statistics_core import WINDOWS, TOTAL_NUMBERS, theoretical_probability

GRADES = tuple("ABCDE")
FORMULA = "marksix_v7_grade_history_v1"
METRICS = ("candidate_counts", "main_hit_counts", "special_hit_counts",
           "hit_counts", "expected_hits")


def grade_history_response(snapshot: AnalysisSnapshot, window=30, include_special=False):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Invalid grade history window")
    probability = theoretical_probability(include_special)
    per_draw = 7 if include_special else 6
    revision = source_revision(snapshot)
    summary = {key: dict.fromkeys(GRADES, 0) for key in METRICS}
    draws = []
    records = snapshot.draws
    # The current V7 uses the last 100 draws. The target and all subsequent
    # draws are excluded, including the target's special ball.
    for index in range(len(records) - 1, max(100, len(records) - window) - 1, -1):
        prior = AnalysisSnapshot(records[index - 100:index])
        partition = {row.number: row.grade
                     for row in _analyze(prior, include_special).numbers}
        if set(partition) != set(range(1, TOTAL_NUMBERS + 1)) or not all(
                grade in GRADES for grade in partition.values()):
            raise ValueError("Invalid V7 grade partition")
        target = records[index]
        candidates = {g: sum(v == g for v in partition.values()) for g in GRADES}
        main_hits = {g: sum(partition[n] == g for n in target.numbers) for g in GRADES}
        special_hits = {g: int(partition[target.special_number] == g) for g in GRADES}
        hits = {g: main_hits[g] + (special_hits[g] if include_special else 0)
                for g in GRADES}
        expected = {g: candidates[g] * per_draw / TOTAL_NUMBERS for g in GRADES}
        row = {**api_draw(target), "grade_cutoff": api_draw(prior.draws[-1]),
               "number_grades": [{"number": n, "grade": partition[n]}
                                 for n in range(1, TOTAL_NUMBERS + 1)],
               "candidate_counts": candidates, "main_hit_counts": main_hits,
               "special_hit_counts": special_hits, "hit_counts": hits,
               "expected_hits": expected}
        draws.append(row)
        for key in METRICS:
            for g in GRADES:
                summary[key][g] += row[key][g]
    complete = len(draws) == window
    return {"status": "ok", "source_revision": revision, "data": {
        "game": "marksix", "schema_version": 1, "engine_version": ENGINE_VERSION,
        "formula_identifier": FORMULA, "grade_basis": "before_draw",
        "include_special": include_special,
        "analysis_mode": "main_plus_special" if include_special else "main_only",
        "numbers_per_draw": per_draw, "total_numbers": TOTAL_NUMBERS,
        "theoretical_probability": probability, "window": window,
        "count": len(draws), "complete_window": complete,
        "incomplete_reason": None if complete else "insufficient_pre_draw_history",
        "latest_draw": api_draw(records[-1]) if records else None,
        "data_snapshot_id": revision.split(":", 1)[1],
        "draws": draws, "summary": summary,
    }}
