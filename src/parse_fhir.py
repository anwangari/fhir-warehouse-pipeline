"""parse_fhir.py — flatten Synthea FHIR bundles into relational CSVs.

v1 scope this commit: Patient. Encounter / Condition / Observation parsers
slot into PARSERS on later days. Implements the mapping in docs/fhir_notes.md.

Run:  python src/parse_fhir.py
"""

import csv
import json
import logging
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("parse_fhir")

RACE_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
ETHNICITY_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"

DATA_DIR = Path("data/fhir")
OUT_DIR = Path("data/csv")


# --- small safe helpers ---------------------------------------------------

def first(seq):
    """First element of a list, or None."""
    return seq[0] if isinstance(seq, list) and seq else None


def resolve_reference(ref):
    """Turn a FHIR reference into a bare id.

        {"reference": "urn:uuid:abc"} -> "abc"
        "Patient/abc"                 -> "abc"
        None / external identifier    -> None

    One helper owns reference handling so the parsers stay simple.
    """
    value = ref.get("reference") if isinstance(ref, dict) else ref
    if not value:
        return None
    if value.startswith("urn:uuid:"):
        return value[len("urn:uuid:"):]
    if "/" in value and "?" not in value:      # "ResourceType/id"
        return value.split("/", 1)[1]
    return None                                # "Practitioner?identifier=..." etc.


def _us_core_display(extensions, url):
    """ombCategory display from a US Core race/ethnicity extension."""
    for ext in extensions or []:
        if ext.get("url") == url:
            for sub in ext.get("extension", []):
                if sub.get("url") == "ombCategory":
                    return sub.get("valueCoding", {}).get("display")
    return None


def coding(concept):
    """(code, display) from the first coding of a CodeableConcept."""
    c = first((concept or {}).get("coding")) or {}
    return c.get("code"), c.get("display")


# --- resource parsers -----------------------------------------------------

def parse_patient(res):
    name = first(res.get("name")) or {}
    address = first(res.get("address")) or {}
    exts = res.get("extension")
    return {
        "patient_id": res.get("id"),
        "family_name": name.get("family"),
        "given_name": first(name.get("given")),
        "gender": res.get("gender"),
        "birth_date": res.get("birthDate"),
        "deceased_date": res.get("deceasedDateTime"),   # None if still living
        "race": _us_core_display(exts, RACE_EXT),
        "ethnicity": _us_core_display(exts, ETHNICITY_EXT),
        "city": address.get("city"),
        "state": address.get("state"),
    }


def parse_encounter(res):
    type_code, type_display = coding(first(res.get("type")))
    period = res.get("period") or {}
    return {
        "encounter_id": res.get("id"),
        "patient_id": resolve_reference(res.get("subject")),
        "class": (res.get("class") or {}).get("code"),
        "type_code": type_code,
        "type_display": type_display,
        "status": res.get("status"),
        "start": period.get("start"),
        "end": period.get("end"),
    }


def parse_condition(res):
    code, display = coding(res.get("code"))
    clin_code, _ = coding(res.get("clinicalStatus"))
    return {
        "condition_id": res.get("id"),
        "patient_id": resolve_reference(res.get("subject")),
        "encounter_id": resolve_reference(res.get("encounter")),
        "code": code,
        "display": display,
        "clinical_status": clin_code,
        "onset_date": res.get("onsetDateTime"),
        "recorded_date": res.get("recordedDate"),
    }


# resourceType -> (parser, target table). Extended on Day 5 (Observation).
PARSERS = {
    "Patient": (parse_patient, "patients"),
    "Encounter": (parse_encounter, "encounters"),
    "Condition": (parse_condition, "conditions"),
}
TABLES = ("patients", "encounters", "conditions")


# --- bundle reading -------------------------------------------------------

def iter_resources(fhir_dir):
    """Yield every resource dict from every bundle file in fhir_dir."""
    for path in sorted(Path(fhir_dir).glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        for entry in bundle.get("entry", []):
            res = entry.get("resource")
            if res:
                yield res


def parse_bundles(fhir_dir=DATA_DIR):
    """Parse all bundles into {table_name: [row, ...]}."""
    tables = {name: [] for name in TABLES}
    seen = Counter()
    for res in iter_resources(fhir_dir):
        rtype = res.get("resourceType")
        seen[rtype] += 1
        handler = PARSERS.get(rtype)
        if not handler:
            continue                            # out of v1 scope; skip harmlessly
        parser, table = handler
        try:
            row = parser(res)
        except Exception as e:                  # fail-soft per resource (DECISIONS #009)
            log.warning("skipped %s %s: %s", rtype, res.get("id"), e)
            continue
        # Every row needs a patient_id: it's the PK for patients and the FK
        # for children. No patient_id -> would be an orphan, so skip and log.
        if not row.get("patient_id"):
            log.warning("skipped %s %s: no patient_id", rtype, res.get("id"))
            continue
        tables[table].append(row)

    log.info("resources seen: %s ...", dict(seen.most_common(5)))
    for name, rows in tables.items():
        log.info("parsed %-12s %d rows", name, len(rows))
    return tables


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        log.warning("no rows for %s", path)
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %s", path)


def main():
    tables = parse_bundles()
    write_csv(tables["patients"], OUT_DIR / "patients.csv")
    write_csv(tables["encounters"], OUT_DIR / "encounters.csv")
    write_csv(tables["conditions"], OUT_DIR / "conditions.csv")


if __name__ == "__main__":
    main()
