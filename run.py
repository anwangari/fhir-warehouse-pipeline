"""run.py — one-command pipeline: (S3) -> parse -> load -> DQ.

Steps:
  0. (optional) land raw bundles in S3   — only if S3_BUCKET is set
  1. parse   bundles      -> data/csv/*.csv
  2. load    CSVs         -> Postgres (schema recreated each run)
  3. dq      gates        -> fails the run on any blocking violation

Idempotent: the load drops & recreates the schema, so re-running yields
identical row counts (see DECISIONS #020).

Run:  python run.py
"""

import logging
import os
import sys
import time
from pathlib import Path

# make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

try:                                   # load .env for DB + S3 config
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import parse_fhir
import load_postgres
import dq_checks

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("run")


def _banner(step, msg):
    log.info("=" * 60)
    log.info("STEP %s — %s", step, msg)
    log.info("=" * 60)


def main():
    t0 = time.time()

    # 0. optional: land raw bundles in S3 before transforming
    bucket = os.getenv("S3_BUCKET")
    if bucket:
        _banner(0, f"land raw bundles in s3://{bucket}")
        import boto3
        import upload_s3
        upload_s3.upload_bundles(boto3.client("s3"), bucket)
    else:
        log.info("STEP 0 — skip S3 (S3_BUCKET not set)")

    # 1. parse bundles -> CSVs
    _banner(1, "parse FHIR bundles -> CSVs")
    parse_fhir.main()

    # 2. load CSVs -> Postgres (schema recreated -> idempotent)
    _banner(2, "load CSVs -> Postgres")
    load_postgres.main()

    # 3. data-quality gates (raises SystemExit(1) on blocking failure)
    _banner(3, "data-quality gates")
    dq_checks.main()

    log.info("=" * 60)
    log.info("PIPELINE COMPLETE in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
