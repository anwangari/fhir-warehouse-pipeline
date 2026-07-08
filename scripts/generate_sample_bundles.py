"""
Generate Synthea-shaped FHIR R4 bundles for offline parser development.

These are DEV FIXTURES, not a replacement for Synthea. They deliberately
mirror the shapes the parser must handle:
  - Bundle -> entry[] -> resource, dispatched by resourceType
  - intra-bundle references via urn:uuid
  - US Core race/ethnicity extensions on Patient
  - Observation value[x] polymorphism (valueQuantity vs valueCodeableConcept)

Usage:
    python scripts/generate_sample_bundles.py --patients 10 --out data/fhir
"""

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

FIRST_NAMES = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer",
               "Michael", "Linda", "David", "Elizabeth", "Maria", "Chen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
              "Miller", "Davis", "Rodriguez", "Martinez", "Okafor", "Nguyen"]

# (code, display) pairs
CONDITIONS = [
    ("44054006", "Diabetes mellitus type 2"),
    ("59621000", "Essential hypertension"),
    ("195967001", "Asthma"),
    ("40055000", "Chronic sinusitis"),
    ("15777000", "Prediabetes"),
]
# quantity observations: (loinc, display, unit, low, high)
OBS_QTY = [
    ("8867-4", "Heart rate", "/min", 55, 100),
    ("8480-6", "Systolic blood pressure", "mm[Hg]", 105, 150),
    ("29463-7", "Body weight", "kg", 55, 110),
    ("2339-0", "Glucose", "mg/dL", 70, 180),
]
# coded observations: (loinc, display, value_code, value_display)
OBS_CODED = [
    ("72166-2", "Tobacco smoking status", "266919005", "Never smoker"),
    ("72166-2", "Tobacco smoking status", "8517006", "Former smoker"),
]
RACE = [("2106-3", "White"), ("2054-5", "Black or African American"),
        ("2028-9", "Asian")]
ETHNICITY = [("2135-2", "Hispanic or Latino"), ("2186-5", "Not Hispanic or Latino")]


def _urn():
    return f"urn:uuid:{uuid.uuid4()}"


def _entry(resource):
    return {"fullUrl": resource["_fullUrl"],
            "resource": {k: v for k, v in resource.items() if k != "_fullUrl"}}


def make_patient():
    ref = _urn()
    gender = random.choice(["male", "female"])
    birth = datetime(1950, 1, 1) + timedelta(days=random.randint(0, 25000))
    race = random.choice(RACE)
    eth = random.choice(ETHNICITY)
    return {
        "_fullUrl": ref,
        "resourceType": "Patient",
        "id": ref.split(":")[-1],
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory",
                            "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238",
                                            "code": race[0], "display": race[1]}}]},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
             "extension": [{"url": "ombCategory",
                            "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238",
                                            "code": eth[0], "display": eth[1]}}]},
        ],
        "name": [{"use": "official",
                  "family": random.choice(LAST_NAMES),
                  "given": [random.choice(FIRST_NAMES)]}],
        "gender": gender,
        "birthDate": birth.strftime("%Y-%m-%d"),
        "address": [{"city": random.choice(["Boston", "Cambridge", "Worcester"]),
                     "state": "MA", "country": "US"}],
    }


def make_encounter(patient_ref, start):
    ref = _urn()
    end = start + timedelta(minutes=random.randint(15, 90))
    return {
        "_fullUrl": ref,
        "resourceType": "Encounter",
        "id": ref.split(":")[-1],
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": random.choice(["AMB", "EMER", "IMP"])},
        "type": [{"coding": [{"system": "http://snomed.info/sct",
                              "code": "162673000", "display": "General examination of patient"}]}],
        "subject": {"reference": patient_ref},
        "period": {"start": start.isoformat() + "Z", "end": end.isoformat() + "Z"},
    }


def make_condition(patient_ref, encounter_ref, onset):
    ref = _urn()
    code, display = random.choice(CONDITIONS)
    return {
        "_fullUrl": ref,
        "resourceType": "Condition",
        "id": ref.split(":")[-1],
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct",
                             "code": code, "display": display}]},
        "subject": {"reference": patient_ref},
        "encounter": {"reference": encounter_ref},
        "onsetDateTime": onset.isoformat() + "Z",
    }


def make_observation_qty(patient_ref, encounter_ref, when):
    ref = _urn()
    loinc, display, unit, low, high = random.choice(OBS_QTY)
    return {
        "_fullUrl": ref,
        "resourceType": "Observation",
        "id": ref.split(":")[-1],
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
        "subject": {"reference": patient_ref},
        "encounter": {"reference": encounter_ref},
        "effectiveDateTime": when.isoformat() + "Z",
        "valueQuantity": {"value": round(random.uniform(low, high), 1),
                          "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }


def make_observation_coded(patient_ref, encounter_ref, when):
    ref = _urn()
    loinc, display, vcode, vdisplay = random.choice(OBS_CODED)
    return {
        "_fullUrl": ref,
        "resourceType": "Observation",
        "id": ref.split(":")[-1],
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
        "subject": {"reference": patient_ref},
        "encounter": {"reference": encounter_ref},
        "effectiveDateTime": when.isoformat() + "Z",
        "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct",
                                             "code": vcode, "display": vdisplay}]},
    }


def make_bundle():
    patient = make_patient()
    p_ref = patient["_fullUrl"]
    entries = [patient]
    for _ in range(random.randint(1, 3)):  # a few encounters per patient
        start = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 500))
        enc = make_encounter(p_ref, start)
        e_ref = enc["_fullUrl"]
        entries.append(enc)
        if random.random() < 0.7:
            entries.append(make_condition(p_ref, e_ref, start))
        for _ in range(random.randint(1, 3)):
            entries.append(make_observation_qty(p_ref, e_ref, start))
        if random.random() < 0.5:
            entries.append(make_observation_coded(p_ref, e_ref, start))
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [_entry(r) for r in entries]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=10)
    ap.add_argument("--out", default="data/fhir")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for i in range(args.patients):
        bundle = make_bundle()
        name = bundle["entry"][0]["resource"]["name"][0]
        fname = f"{name['given'][0]}_{name['family']}_{i}.json"
        (out / fname).write_text(json.dumps(bundle, indent=2))

    print(f"Wrote {args.patients} bundles to {out}/")


if __name__ == "__main__":
    main()
