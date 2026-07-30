"""load_postgres.py — load staged CSVs into Postgres.

Applies the schema, then COPYs each table in FK dependency order
(parents before children) inside a single transaction, and verifies that
DB row counts match the CSVs. Re-runnable: the schema drops & recreates,
so a repeat run yields identical counts.

Config comes from environment variables (see .env.example); defaults match
docker-compose.yml for local dev. No secrets in code.

Run:  python src/load_postgres.py
"""

import csv
import logging
import os
from pathlib import Path

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("load_postgres")

CSV_DIR = Path("data/csv")
SCHEMA_SQL = Path("sql/schema.sql")

# Parents before children so foreign keys always resolve at load time.
LOAD_ORDER = ["patients", "encounters", "conditions", "observations"]


def connect():
    """Connect using env vars; dev defaults match docker-compose.yml."""
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "fhir_dw"),
        user=os.getenv("PGUSER", "fhir"),
        password=os.getenv("PGPASSWORD", "fhir"),
    )


def apply_schema(cur, path=SCHEMA_SQL):
    cur.execute(Path(path).read_text(encoding="utf-8"))
    log.info("applied schema: %s", path)


def copy_table(cur, table, csv_dir=CSV_DIR):
    """Bulk-load one CSV with COPY. Columns taken from the CSV header, so the
    load is robust to column ordering."""
    path = Path(csv_dir) / f"{table}.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        header = f.readline().strip()          # e.g. "patient_id,family_name,..."
        f.seek(0)
        cur.copy_expert(
            f"COPY {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER true)", f
        )
    log.info("loaded %s", table)


def csv_row_count(table, csv_dir=CSV_DIR):
    with (Path(csv_dir) / f"{table}.csv").open("r", encoding="utf-8") as f:
        return sum(1 for _ in f) - 1           # minus header


def verify_counts(cur, csv_dir=CSV_DIR):
    all_ok = True
    for table in LOAD_ORDER:
        cur.execute(f"SELECT count(*) FROM {table}")
        db_n = cur.fetchone()[0]
        csv_n = csv_row_count(table, csv_dir)
        ok = db_n == csv_n
        all_ok = all_ok and ok
        log.info("verify %-12s csv=%d db=%d %s", table, csv_n, db_n,
                 "OK" if ok else "MISMATCH")
    return all_ok


def main():
    conn = connect()
    try:
        # `with conn` is one transaction: commit on success, roll back on error.
        with conn:
            with conn.cursor() as cur:
                apply_schema(cur)
                for table in LOAD_ORDER:
                    copy_table(cur, table)
                if not verify_counts(cur):
                    raise RuntimeError("row-count verification failed — rolled back")
        log.info("load complete")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
