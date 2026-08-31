# Data model — design brief for the ER diagram

A plain-language description of the warehouse's data model, written so a
designer (or a diagram tool) can draw a clean entity-relationship diagram
without reading any code. The authoritative source is `sql/schema.sql`; this
document just translates it.

## The big picture

Four tables. **`patients` is the hub** — every other table describes something
that happened to a patient and points back to it. Draw `patients` centrally;
the other three (`encounters`, `conditions`, `observations`) hang off it.

- **patients** — the person (demographics, birth/death).
- **encounters** — one interaction with the health system (a visit/admission).
- **conditions** — a diagnosis or clinical finding.
- **observations** — a measurement or result (a vital sign, a lab value).

Everything connects through a shared **`patient_id`**. Encounters also connect
conditions and observations to the specific visit they happened in.

---

## Tables and fields

Legend: **PK** = primary key (the unique id of a row) · **FK** = foreign key
(a pointer to another table's PK). Types are simplified: *text*, *date*,
*timestamp*, *number*.

### patients
| Field | Meaning | Key | Type |
|---|---|---|---|
| patient_id | unique id of the person | **PK** | text |
| family_name | last name | | text |
| given_name | first name | | text |
| gender | | | text |
| birth_date | date of birth | | date |
| deceased_date | date of death (empty if living) | | timestamp |
| race | | | text |
| ethnicity | | | text |
| city | | | text |
| state | | | text |

### encounters
| Field | Meaning | Key | Type |
|---|---|---|---|
| encounter_id | unique id of the visit | **PK** | text |
| patient_id | which person (→ patients) | **FK, required** | text |
| class | visit type: AMB / EMER / IMP / HH | | text |
| type_code | coded visit type (SNOMED) | | text |
| type_display | human-readable visit type | | text |
| status | | | text |
| start_time | when the visit began | | timestamp |
| end_time | when it ended | | timestamp |

### conditions
| Field | Meaning | Key | Type |
|---|---|---|---|
| condition_id | unique id of the diagnosis | **PK** | text |
| patient_id | which person (→ patients) | **FK, required** | text |
| encounter_id | visit it was recorded at (→ encounters) | **FK, optional** | text |
| code | diagnosis code (SNOMED) | | text |
| display | human-readable diagnosis | | text |
| clinical_status | active / resolved … | | text |
| onset_date | when it began | | timestamp |
| recorded_date | when it was recorded | | timestamp |

### observations
| Field | Meaning | Key | Type |
|---|---|---|---|
| observation_id | unique id of the measurement | **PK** | text |
| parent_observation_id | groups split panel rows (see note) | | text |
| patient_id | which person (→ patients) | **FK, required** | text |
| encounter_id | visit it was taken at (→ encounters) | **FK, optional** | text |
| category | vital-signs / laboratory … | | text |
| effective | when it was measured | | timestamp |
| code | measurement code (LOINC) | | text |
| display | human-readable measurement | | text |
| value_type | quantity / codeable / string / component | | text |
| value_num | numeric value (e.g. 82.4) | | number |
| value_unit | unit (e.g. mg/dL) | | text |
| value_text | text/coded value | | text |

---

## Relationships (draw these as connectors)

Cardinality in plain terms and in crow's-foot terms:

1. **patients → encounters** — one patient has many encounters. *Required:* every
   encounter belongs to exactly one patient. `one-to-many (mandatory)` →
   crow's foot `||──o<`.
2. **patients → conditions** — one patient has many conditions. *Required.*
   `||──o<`.
3. **patients → observations** — one patient has many observations. *Required.*
   `||──o<`.
4. **encounters → conditions** — one encounter can have many conditions, but a
   condition may have **no** encounter. *Optional.* `zero-or-one to many` →
   crow's foot `o|──o<`.
5. **encounters → observations** — one encounter can have many observations; an
   observation may have no encounter. *Optional.* `o|──o<`.

**Visual cue that matters:** draw the two **required** links (patient_id) as
solid lines and the two **optional** links (encounter_id) as dashed lines. That
single distinction communicates the integrity rules at a glance.

---

## Notes for the designer

- **`parent_observation_id` is not a foreign key** — it just groups rows that
  came from one split panel (e.g. a blood-pressure reading becomes two rows,
  systolic + diastolic, sharing a parent id). If you show it at all, use a
  faint **self-loop** on `observations`, styled differently from the real FKs —
  it's a soft grouping, not an enforced relationship.
- **Key markers:** mark PKs and FKs clearly (a key icon or a small PK/FK tag).
  A column can be listed with its type; keep type labels short (text, date,
  timestamp, number).
- **Hierarchy to convey:** `patients` is the parent of all; `encounters` is a
  secondary hub that also parents conditions and observations. Position
  `patients` prominently and `encounters` between it and the two leaf tables.
- **Match the architecture diagram** — same palette, typography, and line
  weights so the two diagrams read as a set. Suggested: one accent color for
  required relationships, a muted tone for optional/soft ones.
- Keep it clean and scannable: a hiring manager should read the shape in a few
  seconds; detail lives in the field rows, not in decoration.

## Ready-to-import source
A Mermaid `erDiagram` version of exactly this model lives in
`diagrams/schema.mermaid` — paste it into [mermaid.live](https://mermaid.live)
to see the wiring, then restyle from there.
