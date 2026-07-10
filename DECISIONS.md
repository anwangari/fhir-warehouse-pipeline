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

### 007 — Windows for dev, Linux for deploy; enforce LF line endings
**Date:** 2026-07-08
**Context:** Development happens on Windows, but the pipeline deploys to Linux. Mixed CRLF/LF line endings can break shell scripts and produce noisy diffs across the two environments.
**Decision:** Support Windows locally via `docs/setup_windows.md` (PowerShell), keep everything else cross-platform (Docker, `pathlib`, SQL), and add a `.gitattributes` that forces `LF` for all text files in the repo.
**Alternatives considered:** (a) Rely on each dev's `core.autocrlf` git setting; (b) author everything on Linux/WSL only.
**Tradeoff / why:** `.gitattributes` makes line endings a property of the repo, not of each machine's git config — so a file authored on Windows lands as `LF` and runs correctly on the Linux deploy target with no per-dev setup. Relying on `autocrlf` is fragile because it varies by machine. Forcing WSL-only dev adds friction with no benefit for this project's simple toolchain.
**Revisit if:** A tool requires CRLF (e.g. a Windows-only batch file) — scope that exception in `.gitattributes` rather than dropping the global rule.

### 008 — v1 resource scope: Patient, Encounter, Condition, Observation
**Date:** 2026-07-08
**Context:** A Synthea batch emits ~20 resource types (Observation, Procedure, Claim, ExplanationOfBenefit, DiagnosticReport, MedicationRequest, Immunization, …). Parsing all of them is a lot of surface area for a v1.
**Decision:** Scope v1 to the four resources that form the clinical spine — Patient, Encounter, Condition, Observation. All other types pass through unparsed.
**Alternatives considered:** (a) Parse everything Synthea emits; (b) start with Patient only.
**Tradeoff / why:** These four give a complete, join-able clinical story (who / when / what diagnosis / what measurement) and cover the hard parsing problems (reference resolution, `value[x]` polymorphism, US Core extensions). Parsing all 20 types would multiply effort without adding new *kinds* of problem — the marginal resource is just another flatten. Patient-only is too thin to demonstrate FK modeling. Claims are deliberately deferred: they're the subject of Project 2.
**Revisit if:** A portfolio question needs meds or procedures — adding a resource is an additive parse function + table, not a redesign.

### 009 — Normalize Observation value[x] into fixed columns; explode components
**Date:** 2026-07-08
**Context:** FHIR Observations use `value[x]` polymorphism. In the real batch: 21,727 `valueQuantity`, 4,601 `valueCodeableConcept`, 7 `valueString`, and 1,343 with **no top-level value** — panels (e.g. blood pressure) that carry their measurements in `component[]`.
**Decision:** Flatten every observation into fixed columns — `value_type`, `value_num`, `value_unit`, `value_text` — set by the source type. For `component[]`-only panels, emit **one row per component**, using the component's own code and value, keeping the parent code as context.
**Alternatives considered:** (a) Store the raw `value[x]` as JSON and branch in SQL; (b) drop component-only observations; (c) one column per possible type.
**Tradeoff / why:** Fixed columns mean downstream SQL never has to know FHIR's type system — analytics stays simple, which is the project's guiding principle. Exploding components turns nested panels into queryable rows (you can actually query systolic BP), instead of losing 1,343 observations. Storing raw JSON pushes the complexity onto every query; dropping panels loses real clinical data.
**Revisit if:** We need to preserve exact panel grouping — add a `parent_observation_id` column rather than collapsing the explode.

### 010 — Parser structure: dispatch table + single reference resolver
**Date:** 2026-07-08
**Context:** The parser will grow from Patient to four resource types. It needs to stay simple and testable as it grows, and reference handling appears in every child resource.
**Decision:** One `PARSERS` dispatch table maps `resourceType` → (parse function, target table); `iter_resources()` streams resources from files; a single `resolve_reference()` owns all `urn:uuid` / `ResourceType/id` / external-ref logic. Each parser is a pure function `resource dict -> row dict` with safe getters, unit-tested in isolation.
**Alternatives considered:** (a) One big function with `if resourceType == …` branches; (b) a class hierarchy of resource parsers.
**Tradeoff / why:** Pure functions + a dispatch table read at a glance and let each resource be tested with a hand-made fixture — a schema change breaks a test, not production. Centralizing reference resolution means the tricky URN logic lives (and is tested) in one place. A class hierarchy is over-engineered for four flat mappings and works against the project's simplicity principle.
**Revisit if:** Resource count grows large enough that per-type modules beat one file — unlikely for this project.

### 011 — Export Synthea with US Core IG on (regenerate)
**Date:** 2026-07-08
**Context:** The first real batch was exported with `use_us_core_ig false`, so 57/57 real patients lack `us-core-race`/`us-core-ethnicity` extensions — race/ethnicity come out null. These demographics power health-equity analytics, which is exactly the kind of question a provider/payer asks.
**Decision:** Regenerate the batch with `--exporter.fhir.use_us_core_ig true`; update `docs/synthea.md` accordingly. Also purge the Day-1 offline fixture bundles from `data/fhir/` so the batch is pure Synthea.
**Alternatives considered:** (a) Keep US Core off and drop race/ethnicity from scope; (b) leave the fixtures mixed in.
**Tradeoff / why:** US Core is the profile real US healthcare systems actually require, so exporting with it on is both more realistic and unlocks the demographic dimensions. Mixed fixture+real data produced a confusing null pattern and isn't a clean portfolio dataset. Cost is a one-command regenerate. (Parser code is already correct either way — it reads the extensions when present and yields None when absent.)
**Revisit if:** N/A — US Core on is the right default for a US healthcare portfolio.

### 012 — Keep deceased patients; capture deceased_date
**Date:** 2026-07-08
**Context:** Synthea's `-p N` keeps N *living* patients but also exports patients who died during the simulation (this batch: 50 living + 11 deceased = 61). Also learned Synthea appends to the output dir across runs, which had inflated counts until the folder was wiped and regenerated.
**Decision:** Keep deceased patients in the dataset and add a `deceased_date` column (`Patient.deceasedDateTime`, null for the living). Document the "wipe before regenerate" step in `docs/synthea.md`.
**Alternatives considered:** (a) Generate living-only with `--generate.only_alive_patients true`; (b) keep deceased but not record it.
**Tradeoff / why:** Real provider/payer cohorts include the deceased, and mortality is a legitimate analytic dimension (e.g. deaths per condition, age-at-death). Keeping them without a `deceased_date` would make that population invisible downstream, so capturing the date is what gives the choice meaning. Living-only is cleaner for a pure demo but less realistic. Cost is one nullable column.
**Revisit if:** A specific analysis needs living-only — filter on `deceased_date IS NULL` rather than dropping the data at ingest.

### 013 — Encounters/Conditions: keep code + display, generalize orphan-skip
**Date:** 2026-07-08
**Context:** Adding Encounter and Condition parsers. Both carry coded values (SNOMED) and foreign keys to Patient (and Encounter), and Synthea references are all `urn:uuid`. Verified against the real batch: 61 patients, 4,018 encounters, 2,753 conditions, **zero orphan references**.
**Decision:** (1) A single `coding()` helper returns `(code, display)` from the first coding of any CodeableConcept, and both are stored in every coded table. (2) The orphan rule is generalized: **every row must have a `patient_id`** (PK for patients, FK for children); a resource whose patient reference doesn't resolve is skipped and logged rather than loaded. (3) `encounter_id` on a Condition is optional (nullable FK).
**Alternatives considered:** (a) Store only the code and join to a code lookup for display; (b) load orphans with a null FK and clean up later; (c) fail the run on any orphan.
**Tradeoff / why:** Keeping `display` alongside `code` makes CSVs and ad-hoc queries human-readable without a dimension join — worth the small redundancy at this scale. The uniform "no patient_id → skip + log" rule keeps referential integrity at ingest so the warehouse never holds orphan rows, while staying fail-soft per resource (aggregate problems surface in the DQ gates, not as a crash). A code-lookup table is premature normalization; loading orphans defers a problem into the warehouse.
**Revisit if:** Display strings drift from codes and need governance — introduce a code/reference dimension then.
