"""Read-only raw draws and single-number descriptive statistics."""

import logging
import os
from secrets import compare_digest
from datetime import date
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .analysis_engine import build_analysis_foundation
from .analysis_models import AnalysisResponse
from .analysis_response import analysis_response
from .analysis_repository import InvalidCutoff, validate_cutoffs
from .database import DatabaseConfigurationError, DrawRepository
from .models import Draw, RecentDraws
from .draw_sync import freshness, source_revision, synchronize
from .analysis_repository import ANALYSIS_START_DATE, AnalysisDataError, AnalysisRepository, AnalysisSnapshot
from .statistics_core import WINDOWS, InsufficientHistory, draw_counts_response, missing_numbers_response, snapshot_metadata
from .statistics_models import DrawCountsResponse, MissingNumbersResponse, OverviewResponse

logger = logging.getLogger(__name__)
app = FastAPI(title="MarkSix Data API", version="0.1.0")


def get_repository() -> DrawRepository:
    return DrawRepository()


def get_analysis_repository() -> AnalysisRepository:
    return AnalysisRepository()


def get_analysis_snapshot(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
) -> AnalysisSnapshot:
    # Request-scoped dependency, cached by FastAPI within a request only.
    # All calculations consume this immutable object; none reads the DB again.
    return repository.load_analysis_draws()


def get_statistics_window(window: int = 30) -> int:
    if window not in WINDOWS:
        raise HTTPException(status_code=422, detail="window must be 10, 30, 50 or 100")
    return window


@app.exception_handler(InsufficientHistory)
async def insufficient_history(request, exc):
    return JSONResponse(status_code=409, content={"detail": {
        "code": "insufficient_analysis_history",
        "analysis_start_date": ANALYSIS_START_DATE.isoformat(),
        "required_draw_count": exc.required,
        "actual_draw_count": exc.available,
    }})


@app.exception_handler(AnalysisDataError)
async def invalid_analysis_history(request, exc):
    logger.error("Invalid Mark Six analysis history")
    return JSONResponse(status_code=503, content={"detail": "Invalid analysis history"})


@app.exception_handler(DatabaseConfigurationError)
async def database_not_configured(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Mark Six database is not configured"})


@app.exception_handler(psycopg.Error)
async def database_unavailable(request, exc):
    # Do not log connection strings, passwords, or raw driver messages.
    logger.error("Mark Six database unavailable (%s, SQLSTATE=%s)", type(exc).__name__, exc.sqlstate)
    return JSONResponse(status_code=503, content={"detail": "Mark Six database unavailable"})


@app.exception_handler(ValidationError)
async def stored_data_invalid(request, exc):
    logger.error("Invalid Mark Six database draw; response rejected")
    return JSONResponse(status_code=503, content={"detail": "Stored draw failed validation"})


@app.get("/health")
def health():
    # Process liveness only: does not assert database/upstream readiness.
    return {"status": "ok", "service": "marksix"}


@app.get("/api/v1/marksix/freshness")
def draw_freshness(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return freshness()


@app.post("/api/v1/marksix/admin/catch-up")
def admin_catch_up(authorization: Annotated[str | None, Header()] = None):
    token = os.getenv("MARKSIX_CATCH_UP_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Mark Six catch-up disabled")
    if not compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    status, retry = synchronize()
    return JSONResponse(
        status_code={"completed": 200, "in_progress": 202, "cooldown": 429, "retry_later": 503}[status],
        headers={"Retry-After": str(retry)},
        content={"status": status, "retry_after_seconds": retry},
    )


@app.get("/api/v1/marksix/recent-draws", response_model=RecentDraws)
def recent_draws(
    response: Response,
    repository: Annotated[DrawRepository, Depends(get_repository)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    consistent: bool = False,
):
    if consistent:
        snapshot = AnalysisRepository().load_analysis_draws()
        response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
        return {"draws": [row.as_dict() for row in snapshot.newest_first()[:limit]]}
    return {"draws": repository.recent(limit)}


@app.get("/api/v1/marksix/latest", response_model=Draw)
def latest_draw(
    response: Response,
    repository: Annotated[DrawRepository, Depends(get_repository)],
    consistent: bool = False,
):
    if consistent:
        snapshot = AnalysisRepository().load_analysis_draws()
        response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
        draw = snapshot.draws[-1].as_dict() if snapshot.draws else None
    else:
        draw = repository.latest()
    if draw is None:
        raise HTTPException(status_code=404, detail="No Mark Six draws available")
    return draw


@app.get("/api/v1/marksix/draw-counts", response_model=DrawCountsResponse)
def draw_counts(
    response: Response,
    window: Annotated[int, Depends(get_statistics_window)],
    snapshot: Annotated[AnalysisSnapshot, Depends(get_analysis_snapshot)],
    include_special: bool = False,
):
    response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
    return draw_counts_response(snapshot, window, include_special)


@app.get("/api/v1/marksix/missing-numbers", response_model=MissingNumbersResponse)
def missing_numbers(
    response: Response,
    snapshot: Annotated[AnalysisSnapshot, Depends(get_analysis_snapshot)],
    include_special: bool = False,
):
    response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
    return missing_numbers_response(snapshot, include_special)


@app.get("/api/v1/marksix/overview", response_model=OverviewResponse)
def overview(
    response: Response,
    snapshot: Annotated[AnalysisSnapshot, Depends(get_analysis_snapshot)],
):
    """Primary six-number homepage, using exactly one request-scoped snapshot."""
    if not snapshot.draws:
        raise HTTPException(status_code=404, detail="No Mark Six analysis draws available")
    if len(snapshot.draws) < max(WINDOWS):
        raise InsufficientHistory(max(WINDOWS), len(snapshot.draws))
    response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
    return {
        "latest": snapshot.draws[-1].as_dict(),
        "recent_draws": [draw.as_dict() for draw in snapshot.newest_first()[:20]],
        "momentum": {str(window): draw_counts_response(snapshot, window, False)
                     for window in WINDOWS},
        "missing": missing_numbers_response(snapshot, False),
        "analysis": snapshot_metadata(snapshot, False, None, len(snapshot.draws)),
    }


def get_production_analysis_snapshot(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    cutoff_date: date | None = None,
    cutoff_draw: str | None = None,
    include_cutoff_draw: bool = True,
) -> AnalysisSnapshot:
    # Same repository semantics; overview's existing dependency is untouched.
    try:
        validate_cutoffs(cutoff_date, cutoff_draw, include_cutoff_draw)
        snapshot = repository.load_analysis_draws(
            cutoff_date=cutoff_date, cutoff_draw=cutoff_draw,
            include_cutoff_draw=include_cutoff_draw,
        )
    except InvalidCutoff:
        raise HTTPException(status_code=422, detail="Invalid analysis cutoff") from None
    if not isinstance(snapshot, AnalysisSnapshot):
        raise AnalysisDataError("Invalid repository snapshot")
    return snapshot


@app.get("/api/v1/marksix/analysis", response_model=AnalysisResponse)
def production_analysis(
    response: Response,
    snapshot: Annotated[AnalysisSnapshot, Depends(get_production_analysis_snapshot)],
):
    """PRIMARY V7 foundation: current rows, current/previous cutoff metadata."""
    if not snapshot.draws:
        raise HTTPException(status_code=404, detail="No Mark Six analysis draws available")
    response.headers["X-MarkSix-Source-Revision"] = source_revision(snapshot)
    return analysis_response(build_analysis_foundation(snapshot))
