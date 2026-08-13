"""upload_s3.py — land raw FHIR bundles in an S3 landing zone.

Uploads the untouched bundles to:
    s3://<bucket>/<prefix>/ingest_date=YYYY-MM-DD/<file>.json

Raw lands *before* transformation so history can be replayed if the parser
or mapping changes (see DECISIONS #005). Keys are deterministic, so a re-run
overwrites the same objects rather than duplicating them.

Credentials come from the standard AWS chain (~/.aws or env vars) — never
hardcoded. Config via env:  S3_BUCKET (required), S3_PREFIX, INGEST_DATE.

Run:  S3_BUCKET=my-bucket python src/upload_s3.py
"""

import logging
import os
from datetime import date, timezone, datetime
from pathlib import Path

import boto3

try:                                   # optional: load S3_BUCKET / AWS config from .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("upload_s3")

FHIR_DIR = Path("data/fhir")
DEFAULT_PREFIX = "landing/fhir"


def s3_key(prefix, ingest_date, filename):
    """Date-partitioned object key."""
    return f"{prefix}/ingest_date={ingest_date}/{filename}"


def upload_bundles(client, bucket, fhir_dir=FHIR_DIR,
                   prefix=DEFAULT_PREFIX, ingest_date=None):
    """Upload every *.json bundle in fhir_dir; return list of keys written."""
    ingest_date = ingest_date or datetime.now(timezone.utc).date().isoformat()
    files = sorted(Path(fhir_dir).glob("*.json"))
    if not files:
        log.warning("no bundles found in %s", fhir_dir)
        return []

    keys = []
    total_bytes = 0
    for path in files:
        key = s3_key(prefix, ingest_date, path.name)
        client.upload_file(str(path), bucket, key)   # PUT is idempotent by key
        total_bytes += path.stat().st_size
        keys.append(key)

    log.info("uploaded %d bundles (%.1f MB) to s3://%s/%s/ingest_date=%s/",
             len(keys), total_bytes / 1e6, bucket, prefix, ingest_date)
    return keys


def main():
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise SystemExit("S3_BUCKET env var is required (e.g. export S3_BUCKET=my-fhir-landing)")
    prefix = os.getenv("S3_PREFIX", DEFAULT_PREFIX)
    ingest_date = os.getenv("INGEST_DATE")           # optional override; default = today (UTC)

    client = boto3.client("s3")                      # region/creds from AWS default chain
    upload_bundles(client, bucket, prefix=prefix, ingest_date=ingest_date)


if __name__ == "__main__":
    main()
