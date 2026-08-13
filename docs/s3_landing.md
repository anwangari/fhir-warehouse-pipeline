# S3 raw landing zone

Raw, unmodified Synthea bundles are uploaded to S3 **before** transformation
so history can be replayed if the parser or field mapping changes later
(DECISIONS #005). This is the "raw zone first" pattern standard in healthcare
data, where a mapping fix often means reprocessing prior loads.

## Key layout

```
s3://<bucket>/landing/fhir/ingest_date=YYYY-MM-DD/<file>.json
```

Date-partitioned by **ingest date** (Hive-style `key=value` partition), so
each run's raw drop is isolated and discoverable, and partition pruning works
if the zone is ever queried directly (Athena/Glue). Keys are deterministic —
re-running the same day overwrites the same objects rather than duplicating.

## Config (env)

- `S3_BUCKET` (required)
- `S3_PREFIX` (default `landing/fhir`)
- `INGEST_DATE` (default: today, UTC)

Credentials come from the standard AWS chain (`~/.aws/credentials`, AWS_* env
vars, or an instance role) — never hardcoded.

## Least-privilege IAM

The uploader only needs `PutObject` on the landing prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FhirRawLandingPut",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<bucket>/landing/fhir/*"
    }
  ]
}
```

Scope to the exact prefix, grant only `PutObject` (no list/delete/get), and
prefer an IAM role over long-lived keys. Enabling bucket versioning on the
landing zone adds an extra safety net for the immutable-raw guarantee.
