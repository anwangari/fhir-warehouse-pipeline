# FHIR → Warehouse Pipeline

One-line summary: Ingests synthetic FHIR patient bundles, normalizes
them into relational tables, loads to Postgres, and lands raw data in S3.

**Data:** 100% synthetic, generated with Synthea. No real PHI.

### STILL A WORK-IN-PROGRESS (Come back in 2 weeks or less)

## Architecture
![architecture](diagrams/architecture.png)
[Synthea bundles] → [Python parser] → [CSV] → [Postgres] 
                          └→ [raw bundles to S3 landing zone]

## Why this matters (healthcare context)
FHIR is the modern healthcare interoperability standard. Its resources
are deeply nested JSON; turning them into analytics-ready tables is a
core healthcare DE task.

## Stack
Python (json, pandas), PostgreSQL, AWS S3

## How to run
1. `pip install -r requirements.txt`
2. Generate data: <synthea command>
3. Parse: `python src/parse_fhir.py`
4. Load: `python src/load_postgres.py`
5. Query: see `sql/analytics.sql`

## Sample output
<paste one query + its result>

## Key decisions
See DECISIONS.md
