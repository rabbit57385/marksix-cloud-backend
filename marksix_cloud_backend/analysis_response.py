"""Serialize verified foundation values without rounding or re-scoring."""
from .analysis_engine import AnalysisFoundation
from .analysis_models import AnalysisResponse, SCHEMA_VERSION, ENGINE_VERSION
from .analysis_repository import ANALYSIS_START_DATE


def analysis_response(foundation: AnalysisFoundation) -> AnalysisResponse:
    current, previous = foundation.current, foundation.previous
    return AnalysisResponse.model_validate({
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "formula_version": current.formula_version,
            "game": "marksix",
            "include_special": current.include_special,
            "theoretical_probability": current.theoretical_probability,
            "analysis_start_date": ANALYSIS_START_DATE.isoformat(),
            "cutoff_draw": current.cutoff_draw,
            "cutoff_date": current.cutoff_date.isoformat(),
            "previous_cutoff_draw": previous.cutoff_draw,
            "previous_cutoff_date": previous.cutoff_date.isoformat(),
            "available_draw_count": current.available_draw_count,
        },
        "numbers": [{
            "number": row.number,
            "momentum": {"10": row.r10, "30": row.r30, "50": row.r50, "100": row.r100},
            "score": row.score, "grade": row.grade,
            "frozen_score": row.frozen_score, "momentum_type": row.momentum_type,
            "reasons": list(row.reasons), "warnings": list(row.warnings),
        } for row in current.numbers],
    })
