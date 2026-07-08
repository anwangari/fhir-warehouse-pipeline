# DECISIONS.md — Architecture Decision Log

> The most important artifact in this repo. Every meaningful design choice gets an entry here **as it's made**, not after. Each entry is the interview answer to "why did you do it that way?" — so write it like you're explaining it to a technical interviewer.

## Entry format

```
### NNN — <short title>
**Date:** YYYY-MM-DD
**Context:** What problem/decision point prompted this.
**Decision:** What I chose.
**Alternatives considered:** What I rejected.
**Tradeoff / why:** Why the choice wins here, and what it costs.
**Revisit if:** The condition that would change this decision.
```

Number entries sequentially. Never delete an entry — if a decision is reversed, add a new entry that supersedes it and reference the old number.

---

### 001 — Synthea as the data source
**Date:** 2026-07-08
**Context:** The pipeline needs realistic FHIR input to parse and load, but this is a healthcare project where PHI risk is unacceptable.
**Decision:** Generate all input with Synthea (FHIR R4 bundles).
**Alternatives considered:** (a) Hand-rolled fixture bundles only; (b) real de-identified datasets.
**Tradeoff / why:** Synthea produces standards-compliant FHIR with referential integrity across resources (Patient ↔ Encounter ↔ Condition ↔ Observation), so the parser is exercised against the same nesting and reference patterns a real feed would throw — with zero PHI risk. Hand-rolled fixtures are too clean to be a real test; real data carries compliance risk not worth taking for a portfolio project. Small hand-made fixtures are still used, but only for unit tests.
**Revisit if:** I need a specific edge case Synthea doesn't emit — then add a targeted hand-made fixture for that case.

### 002 — Start at 50 patients
**Date:** 2026-07-08
**Context:** Synthea can generate any volume; need to pick a starting batch size.
**Decision:** Begin with ~50 patients, single state, FHIR R4.
**Alternatives considered:** Start at 1,000+ patients.
**Tradeoff / why:** 50 patients keeps the parse/load loop fast during development so iteration is cheap, while still covering the resource variety I care about. Regenerating at 1,000+ later is a one-line change and gives a "does it still hold at scale?" talking point without paying the iteration cost up front.
**Revisit if:** I want to demonstrate load performance / indexing benefits — bump the volume once the pipeline is correct.

### 003 — PostgreSQL in Docker for the warehouse
**Date:** 2026-07-08
**Context:** Need a warehouse target that's realistic, reproducible, and free to run locally.
**Decision:** PostgreSQL running in a local Docker container.
**Alternatives considered:** (a) SQLite; (b) a local Postgres install; (c) cloud RDS from day one.
**Tradeoff / why:** Postgres gives real DDL — explicit types, PKs/FKs, indexes — which is the point of the project; SQLite is too forgiving to prove data-modeling skill. Docker makes the environment reproducible and disposable (anyone can `docker compose up`), avoids polluting the host, and mirrors how a real dev environment is stood up. Cloud RDS adds cost and setup friction with no learning benefit for a batch-parse project; S3 is the only cloud dependency needed here.
**Revisit if:** The arc needs a managed-warehouse story (Redshift/Snowflake) — that belongs in a later project, not this one.

### 004 — CSV as the intermediate staging format
**Date:** 2026-07-08
**Context:** The parser turns nested FHIR JSON into flat tables; those need to reach Postgres somehow.
**Decision:** Parser writes CSVs to `data/csv/`, and a separate loader step loads CSVs into Postgres.
**Alternatives considered:** (a) Load parsed JSON straight into Postgres in one step; (b) Parquet as the intermediate.
**Tradeoff / why:** A CSV staging step makes the transform inspectable (I can open the output and eyeball it) and unit-testable independent of the database, which cleanly separates extract/transform from load. CSV is human-readable and `COPY`-friendly. Parquet would be faster/typed but adds a dependency and hides the data behind tooling — not worth it at this volume. One-step JSON→DB couples parsing and loading and makes failures harder to localize.
**Revisit if:** Data volume grows enough that CSV I/O or type-loss becomes a real cost — then switch the intermediate to Parquet.

### 005 — Land raw bundles in S3 before transforming
**Date:** 2026-07-08
**Context:** Deciding whether raw FHIR bundles are persisted anywhere or just parsed and discarded.
**Decision:** Upload raw, unmodified bundles to an S3 landing zone (date-partitioned keys) *before* the transform runs.
**Alternatives considered:** Parse in place and keep only the warehouse tables.
**Tradeoff / why:** A raw immutable landing zone means history can be replayed if the parser or field mapping changes later — reprocess from raw instead of regenerating. It also gives an audit trail and a schema-on-read fallback. This raw-zone-first pattern is standard in healthcare, where a mapping fix often requires reprocessing prior loads. Cost is a little extra storage and an upload step — negligible for the value.
**Revisit if:** N/A for this project — this is a keeper pattern for the whole arc.

### 006 — Offline fixture generator alongside Synthea
**Date:** 2026-07-08
**Context:** Synthea is the real data source, but it needs Java + a ~15 MB download. Parser development shouldn't be blocked when that environment isn't available.
**Decision:** Keep Synthea as the primary/portfolio data path (documented in `docs/synthea.md`), and add `scripts/generate_sample_bundles.py` that emits Synthea-shaped R4 bundles for offline development.
**Alternatives considered:** (a) Only use Synthea; (b) commit a few static sample bundles.
**Tradeoff / why:** The generator deliberately reproduces the shapes the parser must handle — `urn:uuid` intra-bundle references, US Core race/ethnicity extensions, and Observation `value[x]` polymorphism — so parser logic is exercised against realistic edge cases with no external dependency. It's labeled a dev fixture, not a Synthea substitute; the portfolio run still uses Synthea. Static committed bundles were rejected because a seedable generator gives controllable variety and volume. Generated data stays under `data/` and is gitignored.
**Revisit if:** Synthea coverage is always available in the working environment — then the generator is only needed for unit-test fixtures.
