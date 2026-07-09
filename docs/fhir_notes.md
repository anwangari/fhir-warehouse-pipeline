# FHIR notes — resource/field mapping

Field-level map from Synthea FHIR R4 bundles to the flat tables the parser
produces. This is the contract `src/parse_fhir.py` implements. Paths use dot
notation; `[0]` means "first element of an array".

> Based on a real Synthea batch: **67 patients / 69 bundle files**
> (the 2 extra files are `hospitalInformation*.json` and
> `practitionerInformation*.json` — see "Non-patient bundles" below).

## Bundle envelope

Every file is:

```
Bundle
└── entry[]                       # list of wrapped resources
    ├── fullUrl                   # "urn:uuid:<id>" — the resource's in-bundle identity
    └── resource
        └── resourceType          # dispatch key: Patient | Encounter | Condition | Observation | ...
```

The parser iterates files → `entry[]` → `resource`, and **dispatches on
`resource.resourceType`**. Anything not in scope is skipped harmlessly.

Observed resource types (this batch): Observation (27,678), Procedure,
Claim, ExplanationOfBenefit, DiagnosticReport, Encounter (3,118),
MedicationRequest, Condition (2,129), Immunization, Patient (67),
AllergyIntolerance, plus infra (Organization, Practitioner, Location).

## v1 scope

Extract **Patient, Encounter, Condition, Observation**. Everything else
(Procedure, MedicationRequest, Claim, Immunization, …) is out of scope for
v1 and passes through unparsed. Rationale is in DECISIONS.md #008.

## The reference / join model

Resources point at each other by reference. In Synthea, **within a bundle
all references are `urn:uuid:<id>`** (confirmed: 100% of Encounter/Condition/
Observation subjects use this style in the batch).

- A resource's identity is its `id` (equal to the UUID inside its `fullUrl`).
- A reference like `subject.reference = "urn:uuid:a7c2...eab65"` points to the
  Patient whose `id` is `a7c2...eab65`.
- **Join key rule:** strip the `urn:uuid:` prefix (or a `ResourceType/`
  prefix if present) → that's the foreign key. One helper, `resolve_reference()`,
  owns this so the rest of the parser stays dumb.

Some references point outside the bundle by business identifier, e.g.
`"Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999943696"` — these
are out of v1 scope and ignored.

## patients

| Column        | JSON path                                                                 | Notes |
|---------------|---------------------------------------------------------------------------|-------|
| `patient_id`  | `id`                                                                       | PK; same UUID as `fullUrl` |
| `family_name` | `name[0].family`                                                           | |
| `given_name`  | `name[0].given[0]`                                                         | Synthea appends digits, e.g. `Adrian111` |
| `gender`      | `gender`                                                                   | male / female |
| `birth_date`  | `birthDate`                                                                | `YYYY-MM-DD` |
| `race`        | `extension[url=…us-core-race].extension[url=ombCategory].valueCoding.display` | US Core extension |
| `ethnicity`   | `extension[url=…us-core-ethnicity].extension[url=ombCategory].valueCoding.display` | US Core extension |
| `city`        | `address[0].city`                                                          | |
| `state`       | `address[0].state`                                                         | |

Ignored: `text`, `identifier[]`, mothersMaidenName/birthPlace extensions,
`telecom`, `communication`, `maritalStatus`, `multipleBirth`.

## encounters

| Column         | JSON path                                | Notes |
|----------------|------------------------------------------|-------|
| `encounter_id` | `id`                                     | PK |
| `patient_id`   | resolve(`subject.reference`)             | FK → patients |
| `class`        | `class.code`                             | AMB / EMER / IMP … |
| `type_code`    | `type[0].coding[0].code`                 | SNOMED |
| `type_display` | `type[0].coding[0].display`              | |
| `status`       | `status`                                 | usually `finished` |
| `start`        | `period.start`                           | ISO 8601 w/ offset |
| `end`          | `period.end`                             | may be absent |

Ignored: `participant[]`, `serviceProvider`, `reasonCode`, `location`.

## conditions

| Column            | JSON path                          | Notes |
|-------------------|------------------------------------|-------|
| `condition_id`    | `id`                               | PK |
| `patient_id`      | resolve(`subject.reference`)       | FK → patients |
| `encounter_id`    | resolve(`encounter.reference`)     | FK → encounters (usually present) |
| `code`            | `code.coding[0].code`              | SNOMED |
| `display`         | `code.coding[0].display`           | |
| `clinical_status` | `clinicalStatus.coding[0].code`    | active / resolved |
| `onset_date`      | `onsetDateTime`                    | may be absent |
| `recorded_date`   | `recordedDate`                     | |

⚠️ Synthea encodes some **social-determinant "findings" as Conditions**
(e.g. "Educated to high school level"). v1 keeps all of them and captures
`code`/`display` as-is; filtering clinical-vs-social is a documented future
step, not a v1 concern.

## observations

The trickiest table because of `value[x]` polymorphism. Three shapes seen:

| Value shape             | Count  | Where the value lives |
|-------------------------|--------|-----------------------|
| `valueQuantity`         | 21,727 | `valueQuantity.value` + `.unit` |
| `valueCodeableConcept`  | 4,601  | `valueCodeableConcept.coding[0].code` / `.display` |
| `valueString`           | 7      | `valueString` |
| **`component[]` only**  | 1,343  | **no top-level value** — sub-measurements in `component[]` (e.g. BP panel → systolic + diastolic) |

Base columns:

| Column           | JSON path                        | Notes |
|------------------|----------------------------------|-------|
| `observation_id` | `id`                             | PK |
| `patient_id`     | resolve(`subject.reference`)     | FK → patients |
| `encounter_id`   | resolve(`encounter.reference`)   | FK → encounters |
| `code`           | `code.coding[0].code`            | LOINC |
| `display`        | `code.coding[0].display`         | |
| `category`       | `category[0].coding[0].code`     | vital-signs / laboratory … |
| `effective`      | `effectiveDateTime`              | |
| `value_type`     | derived                          | `quantity` / `codeable` / `string` / `component` |
| `value_num`      | `valueQuantity.value`            | null unless quantity |
| `value_unit`     | `valueQuantity.unit`             | null unless quantity |
| `value_text`     | `valueCodeableConcept…display` or `valueString` | null unless coded/string |

**Handling decision (DECISIONS.md #009):** normalize every observation into
fixed columns (`value_type`, `value_num`, `value_unit`, `value_text`) so
downstream SQL never branches on FHIR type. For `component[]`-only
observations (panels), v1 emits **one row per component** — the component's
own `code`/value populates the value columns, with the parent's `code` kept
as context. This turns a nested panel into flat, queryable rows.

## Missing / optional field policy

- Use safe getters — a missing optional path yields `None`, never a crash.
- **Required for a row to exist:** `id` and a resolvable `patient_id`
  (except Patient itself). A child resource with no resolvable patient is
  **skipped and logged**, not loaded — it would be an orphan FK.
- Optional fields (`end`, `onsetDateTime`, `encounter` on a Condition) → `None`.
- A resource that fails to parse is skipped and counted; the run continues.
  Counts are logged per resource type so drops are visible. (fail-soft on
  individual resources, fail-loud via DQ gates on aggregate problems — see #009.)

## Non-patient bundles

Synthea also emits `hospitalInformation*.json` and
`practitionerInformation*.json` (Organization / Practitioner / Location).
Because the parser dispatches on `resourceType` and v1 ignores those types,
these files are read and produce no rows — no special-casing needed.
