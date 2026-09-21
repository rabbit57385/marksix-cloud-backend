"""Explicit CLI updater; never runs at import or FastAPI startup."""

import argparse
import json
import logging

import psycopg
from pydantic import ValidationError

if __package__:
    from .database import DatabaseConfigurationError, connect_database, database_url, store_draw
    from .hkjc_client import HkjcError, fetch_recent_draws
    from .models import validate_draw
else:
    from database import DatabaseConfigurationError, connect_database, database_url, store_draw
    from hkjc_client import HkjcError, fetch_recent_draws
    from models import validate_draw

logger = logging.getLogger(__name__)


def empty_stats() -> dict:
    return {"inserted": 0, "existing": 0, "conflict": 0, "failed": 0}


def import_draws(connection, draws) -> dict:
    """Each record is its own transaction; commit failures count as failed.

    Failed transactions roll back before the next record. Existing rows are
    never overwritten, and conflicts include field-by-field public draw data.
    """
    stats = empty_stats()
    for index, value in enumerate(draws):
        try:
            draw = validate_draw(value)
            outcome, difference = store_draw(connection, draw)
        except (ValidationError, ValueError, TypeError) as exc:
            stats["failed"] += 1
            logger.error("Record %s failed validation/configuration (%s)", index, type(exc).__name__)
            continue
        except psycopg.Error as exc:
            stats["failed"] += 1
            logger.error("Record %s database failure (%s, SQLSTATE=%s)",
                         index, type(exc).__name__, exc.sqlstate)
            continue
        except RuntimeError as exc:
            stats["failed"] += 1
            logger.error("Record %s could not be compared safely (%s)", index, type(exc).__name__)
            continue
        stats[outcome] += 1
        if outcome == "conflict":
            logger.warning("Draw %s conflict; database preserved; differences=%s",
                           draw["draw"], json.dumps(difference, ensure_ascii=True))
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import recent official HKJC Mark Six draws")
    parser.add_argument("--last-n", type=int, default=20, help="Recent draws to request (1..200)")
    args = parser.parse_args(argv)
    if not 1 <= args.last_n <= 200:
        parser.error("--last-n must be in 1..200")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = empty_stats()
    try:
        # Fail before fetching HKJC if destination has not been explicitly set.
        database_url()
        draws = fetch_recent_draws(args.last_n)
        with connect_database() as connection:
            stats = import_draws(connection, draws)
    except HkjcError as exc:
        logger.error("HKJC request failed: %s", json.dumps(exc.diagnostics, ensure_ascii=True))
        print(json.dumps({**stats, "batch_error": exc.kind}))
        return 1
    except DatabaseConfigurationError:
        logger.error("DATABASE_URL must point to a dedicated initialized Mark Six database")
        print(json.dumps({**stats, "batch_error": "database_not_configured"}))
        return 1
    except psycopg.Error as exc:
        logger.error("Database connection failure (%s, SQLSTATE=%s)", type(exc).__name__, exc.sqlstate)
        print(json.dumps({**stats, "batch_error": "database_unavailable"}))
        return 1
    print(json.dumps(stats))
    return 1 if stats["conflict"] or stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
