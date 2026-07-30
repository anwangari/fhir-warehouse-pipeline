-- schema.sql — FHIR warehouse DDL
-- Normalized relational model: patients + three child tables.
-- Column order matches the parser's CSV headers so COPY ... WITH HEADER loads directly.
-- Idempotent: drop and recreate so the schema can be re-applied cleanly.
-- See DECISIONS.md #015 for the design rationale.

DROP TABLE IF EXISTS observations CASCADE;
DROP TABLE IF EXISTS conditions  CASCADE;
DROP TABLE IF EXISTS encounters  CASCADE;
DROP TABLE IF EXISTS patients    CASCADE;

-- ---------------------------------------------------------------------------
-- patients (parent of everything)
-- ---------------------------------------------------------------------------
CREATE TABLE patients (
    patient_id     TEXT PRIMARY KEY,
    family_name    TEXT,
    given_name     TEXT,
    gender         TEXT,
    birth_date     DATE,
    deceased_date  TIMESTAMPTZ,          -- NULL = still living
    race           TEXT,
    ethnicity      TEXT,
    city           TEXT,
    state          TEXT
);

-- ---------------------------------------------------------------------------
-- encounters (one interaction with the health system)
-- ---------------------------------------------------------------------------
CREATE TABLE encounters (
    encounter_id   TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients (patient_id),
    class          TEXT,                 -- AMB | EMER | IMP ...
    type_code      TEXT,                 -- SNOMED
    type_display   TEXT,
    status         TEXT,
    start_time     TIMESTAMPTZ,
    end_time       TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- conditions (diagnoses & findings)
-- ---------------------------------------------------------------------------
CREATE TABLE conditions (
    condition_id    TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients (patient_id),
    encounter_id    TEXT REFERENCES encounters (encounter_id),   -- optional
    code            TEXT,                -- SNOMED
    display         TEXT,
    clinical_status TEXT,                -- active | resolved ...
    onset_date      TIMESTAMPTZ,
    recorded_date   TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- observations (measurements & results; panels exploded to one row/component)
-- ---------------------------------------------------------------------------
CREATE TABLE observations (
    observation_id         TEXT PRIMARY KEY,   -- component rows use "<id>#<i>"
    parent_observation_id  TEXT,               -- panel grouping; NOT a FK (panel base row isn't stored)
    patient_id             TEXT NOT NULL REFERENCES patients (patient_id),
    encounter_id           TEXT REFERENCES encounters (encounter_id),
    category               TEXT,               -- vital-signs | laboratory ...
    effective              TIMESTAMPTZ,
    code                   TEXT,               -- LOINC
    display                TEXT,
    value_type             TEXT,               -- quantity | codeable | string | component
    value_num              NUMERIC,
    value_unit             TEXT,
    value_text             TEXT
);

-- ---------------------------------------------------------------------------
-- Indexes: foreign keys (join paths) + common analytic filters
-- ---------------------------------------------------------------------------
CREATE INDEX idx_encounters_patient   ON encounters  (patient_id);
CREATE INDEX idx_encounters_start     ON encounters  (start_time);

CREATE INDEX idx_conditions_patient   ON conditions  (patient_id);
CREATE INDEX idx_conditions_encounter ON conditions  (encounter_id);
CREATE INDEX idx_conditions_code      ON conditions  (code);

CREATE INDEX idx_observations_patient   ON observations (patient_id);
CREATE INDEX idx_observations_encounter ON observations (encounter_id);
CREATE INDEX idx_observations_code      ON observations (code);
-- "latest value per patient for a given test" is a core query -> composite
CREATE INDEX idx_observations_patient_code ON observations (patient_id, code);
