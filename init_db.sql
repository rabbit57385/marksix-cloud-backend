-- Run manually ONLY against a dedicated Mark Six PostgreSQL database.
-- This is a one-time schema initializer, not an automatic application migration.
-- Re-running against an existing table fails instead of hiding schema drift.
BEGIN;

CREATE SCHEMA IF NOT EXISTS marksix;

CREATE TABLE marksix.draws (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    draw VARCHAR(6) NOT NULL,
    draw_date DATE NOT NULL,
    number1 SMALLINT NOT NULL,
    number2 SMALLINT NOT NULL,
    number3 SMALLINT NOT NULL,
    number4 SMALLINT NOT NULL,
    number5 SMALLINT NOT NULL,
    number6 SMALLINT NOT NULL,
    special_number SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT marksix_draw_unique UNIQUE (draw),
    CONSTRAINT marksix_draw_format CHECK (
        draw ~ '^[0-9]{2}/[0-9]{3}$' AND right(draw, 3) <> '000'
    ),
    CONSTRAINT marksix_draw_year CHECK (
        left(draw, 2) = right(extract(year FROM draw_date)::text, 2)
    ),
    CONSTRAINT marksix_main_range CHECK (
        number1 BETWEEN 1 AND 49 AND number2 BETWEEN 1 AND 49
        AND number3 BETWEEN 1 AND 49 AND number4 BETWEEN 1 AND 49
        AND number5 BETWEEN 1 AND 49 AND number6 BETWEEN 1 AND 49
    ),
    -- All 15 pairwise comparisons, within this row only; no subqueries/UDFs.
    CONSTRAINT marksix_main_distinct CHECK (
        number1 <> ALL (ARRAY[number2, number3, number4, number5, number6])
        AND number2 <> ALL (ARRAY[number3, number4, number5, number6])
        AND number3 <> ALL (ARRAY[number4, number5, number6])
        AND number4 <> ALL (ARRAY[number5, number6])
        AND number5 <> number6
    ),
    CONSTRAINT marksix_special_range CHECK (special_number BETWEEN 1 AND 49),
    CONSTRAINT marksix_special_distinct CHECK (
        special_number <> ALL (ARRAY[number1, number2, number3, number4, number5, number6])
    )
);

CREATE INDEX marksix_draws_recent_idx ON marksix.draws (draw_date DESC, draw DESC);

CREATE FUNCTION marksix.touch_draw_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER marksix_draws_updated_at
BEFORE UPDATE ON marksix.draws
FOR EACH ROW EXECUTE FUNCTION marksix.touch_draw_updated_at();

COMMIT;
