"""Explicit Mark Six schema access; never initialize/migrate at import/startup."""

import os
from datetime import date

import psycopg
from psycopg.rows import dict_row

if __package__:
    from .models import validate_draw
else:
    from models import validate_draw


class DatabaseConfigurationError(RuntimeError):
    pass


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise DatabaseConfigurationError("DATABASE_URL is required for a dedicated Mark Six database")
    return value


def connect_database():
    # Explicit transactions in store_draw commit one draw at a time.
    # Read committed makes a concurrent ON CONFLICT winner visible to SELECT.
    connection = psycopg.connect(
        database_url(),
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=10,
        options="-c statement_timeout=15000",
    )
    connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    return connection


SELECT_COLUMNS = "draw, draw_date, number1, number2, number3, number4, number5, number6, special_number"
INSERT_SQL = """
    INSERT INTO marksix.draws
        (draw, draw_date, number1, number2, number3, number4, number5, number6, special_number)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (draw) DO NOTHING
    RETURNING id
"""


def row_to_draw(row: dict) -> dict:
    raw_date = row["draw_date"]
    return validate_draw({
        "draw": row["draw"],
        "date": raw_date.isoformat() if isinstance(raw_date, date) else raw_date,
        "numbers": [row[f"number{i}"] for i in range(1, 7)],
        "special_number": row["special_number"],
    })


def store_draw(connection, value: object) -> tuple[str, dict]:
    """Insert or compare; never UPDATE existing data, even on source corrections.

    Requires an autocommit connection with no ambient transaction, so the
    successful return follows COMMIT rather than just release of a savepoint.
    """
    draw = validate_draw(value)
    if not connection.autocommit:
        raise ValueError("store_draw requires an autocommit connection")
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("store_draw cannot run inside an existing transaction")
    with connection.transaction():
        with connection.cursor() as cursor:
            outcome, difference = insert_or_compare(cursor, draw)
    return outcome, difference


def insert_or_compare(cursor, value: object) -> tuple[str, dict]:
    """Caller owns the transaction. Used by per-draw and atomic monthly imports."""
    draw = validate_draw(value)
    params = (draw["draw"], draw["date"], *draw["numbers"], draw["special_number"])
    cursor.execute(INSERT_SQL, params)
    if cursor.fetchone() is not None:
        return "inserted", {}
    cursor.execute(
        f"SELECT {SELECT_COLUMNS} FROM marksix.draws WHERE draw = %s FOR SHARE",
        (draw["draw"],),
    )
    existing = cursor.fetchone()
    if existing is None:
        raise RuntimeError("Conflicting draw disappeared before comparison; retry explicitly")
    saved = row_to_draw(existing)
    difference = {
        key: {"database": saved[key], "hkjc": draw[key]}
        for key in ("date", "numbers", "special_number") if saved[key] != draw[key]
    }
    return ("conflict" if difference else "existing"), difference


class DrawRepository:
    def recent(self, limit: int) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer in 1..200")
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {SELECT_COLUMNS} FROM marksix.draws "
                    "ORDER BY draw_date DESC, draw DESC LIMIT %s",
                    (limit,),
                )
                return [row_to_draw(row) for row in cursor.fetchall()]

    def latest(self) -> dict | None:
        draws = self.recent(1)
        return draws[0] if draws else None
