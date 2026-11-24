"""Bounded official-history synchronization shared by cron and authenticated catch-up."""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import psycopg
from pydantic import ValidationError

from .analysis_repository import ANALYSIS_START_DATE, AnalysisSnapshot
from .database import SELECT_COLUMNS, connect_database, insert_or_compare, row_to_draw
from .hkjc_client import HkjcError, fetch_draws_by_date_range

logger = logging.getLogger(__name__)
LOCK = 786931651442193
COOLDOWN = 180
LOOKBACK = 90
OFFICIAL_CHECK_MAX_AGE = timedelta(hours=26)
HONG_KONG = timezone(timedelta(hours=8))
STATE = "marksix.draw_sync_state"


def source_revision(snapshot):
    payload = [[d.draw, d.date.isoformat(), sorted(d.numbers), d.special_number]
               for d in snapshot.draws]
    digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return f"marksix-source-v1:{digest}"


def snapshot(cursor):
    cursor.execute(
        f"SELECT {SELECT_COLUMNS} FROM marksix.draws WHERE draw_date >= %s "
        "ORDER BY draw_date ASC, draw ASC", (ANALYSIS_START_DATE,),
    )
    return AnalysisSnapshot.from_records([row_to_draw(row) for row in cursor.fetchall()])


def remaining(state, now):
    after = state["retry_at"]
    if after is None or after <= now:
        return 0
    return int((after - now + timedelta(seconds=1) - timedelta(microseconds=1)).total_seconds())


def read_state(cursor):
    cursor.execute(f"SELECT * FROM {STATE} WHERE singleton")
    state = cursor.fetchone()
    if state is None:
        raise RuntimeError("Apply the MarkSix sync migration before enabling synchronization")
    return state


def api_draw(draw):
    if draw is None:
        return None
    return {"draw_no": draw.draw, "draw_date": draw.date.isoformat(),
            "numbers": list(draw.numbers), "special_number": draw.special_number}


def freshness():
    with connect_database() as connection, connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        state = read_state(cursor)
        current = snapshot(cursor)
        # Probe the same transaction-scoped lock used by all admitted workers.
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s) AS acquired", (LOCK,))
        busy = not cursor.fetchone()["acquired"]
    now = datetime.now(timezone.utc)
    latest = api_draw(current.draws[-1] if current.draws else None)
    revision = source_revision(current)
    verified = state["verified_revision"] == revision and latest is not None
    checked = state["last_check_at"]
    recent_check = checked is not None and now - checked <= OFFICIAL_CHECK_MAX_AGE
    status = ("catching_up" if busy else "failed" if state["last_error"] else
              "up_to_date" if verified and recent_check else "stale" if checked else "unknown")
    return {
        "status": status, "sync_revision": state["sync_revision"],
        "source_revision": revision, "latest_draw": latest,
        "latest_verified_draw": latest if verified else None,
        "last_official_check_at": state["last_check_at"],
        "last_successful_sync_at": state["last_success_at"],
        "sync_in_progress": busy, "retry_after_seconds": remaining(state, now),
        "last_error": state["last_error"],
        "completeness": {
            "from": state["verified_from"], "through": state["verified_through"],
            "scope": "published_official_month_range", "global_history_verified": False,
        },
    }


def fetch_months(start, end, fetch):
    # HKJC returns empty for multi-month ranges even when monthly queries work.
    rows = []
    first = start
    while first <= end:
        following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = min(end, following - timedelta(days=1))
        part = fetch(first, last)
        if any(not first.isoformat() <= draw["date"] <= last.isoformat() for draw in part):
            raise ValueError("Official results outside requested month")
        rows.extend(part)
        first = following
    return rows


def synchronize(*, fetch=fetch_draws_by_date_range, connect=connect_database):
    """Bounded official monthly reads and an atomic batch; failures retain prior data."""
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (LOCK,))
        if not cursor.fetchone()["acquired"]:
            return "in_progress", 15
        state = read_state(cursor)
        now = datetime.now(timezone.utc)
        retry = remaining(state, now)
        if retry:
            return "cooldown", retry
        # Persist admission before contacting HKJC. A killed worker releases
        # its session lock but the next worker still respects the cooldown.
        cursor.execute(
            f"UPDATE {STATE} SET retry_at=clock_timestamp() + "
            "(%s * interval '1 second') WHERE singleton",
            (COOLDOWN,),
        )
        today = now.astimezone(HONG_KONG).date()
        start = (today - timedelta(days=LOOKBACK)).replace(day=1)
        try:
            # Roll back every proposed draw on conflict or a failed insert.
            with connection.transaction():
                official = fetch_months(start, today, fetch)
                if not official:
                    raise ValueError("Official history was empty")
                # Official response must cover the complete requested interval.
                # Detect truncation by requiring contiguous issue numbers within a year.
                ordered = sorted(official, key=lambda d: (d["date"], d["draw"]))
                for left, right in zip(ordered, ordered[1:]):
                    ly, ln = map(int, left["draw"].split("/"))
                    ry, rn = map(int, right["draw"].split("/"))
                    if (ly == ry and rn != ln + 1) or (ly != ry and rn != 1):
                        raise ValueError("Official result cohort has a gap")
                current = snapshot(cursor)
                official_by_issue = {d["draw"]: d for d in official}
                if len(official_by_issue) != len(official):
                    raise ValueError("Duplicate official draw")
                for draw in current.draws:
                    if draw.date >= start and draw.draw not in official_by_issue:
                        raise ValueError("Official cohort does not cover stored interval")
                for draw in ordered:
                    outcome, _ = insert_or_compare(cursor, draw)
                    if outcome == "conflict":
                        raise ValueError("Official draw conflicts with stored result")
                current = snapshot(cursor)
                revision = source_revision(current)
                cursor.execute(
                    f"UPDATE {STATE} SET last_check_at=clock_timestamp(), last_success_at=clock_timestamp(), "
                    "last_error=NULL, retry_at=clock_timestamp() + (%s * interval '1 second'), "
                    "sync_revision=sync_revision + CASE WHEN verified_revision IS DISTINCT FROM %s THEN 1 ELSE 0 END, "
                    "verified_revision=%s, verified_from=%s, verified_through=%s WHERE singleton",
                    (COOLDOWN, revision, revision, start, ordered[-1]["date"]),
                )
        except (HkjcError, psycopg.Error, ValidationError, ValueError, RuntimeError) as exc:
            logger.warning("MarkSix synchronization failed (%s)", type(exc).__name__)
            cursor.execute(
                f"UPDATE {STATE} SET last_check_at=clock_timestamp(), last_error='sync_failed', "
                "retry_at=clock_timestamp() + (%s * interval '1 second') WHERE singleton",
                (COOLDOWN,),
            )
            return "retry_later", COOLDOWN
        return "completed", COOLDOWN


def main():
    logging.basicConfig(level=logging.INFO)
    status, retry = synchronize()
    print(json.dumps({"status": status, "retry_after_seconds": retry}))
    return int(status == "retry_later")


if __name__ == "__main__":
    raise SystemExit(main())
