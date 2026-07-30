"""Unit tests for the FHIR parser (Day 3 scope: references + patients)."""

import json

import parse_fhir as pf


# --- resolve_reference ----------------------------------------------------

def test_resolve_urn_uuid():
    assert pf.resolve_reference({"reference": "urn:uuid:abc-123"}) == "abc-123"


def test_resolve_relative_reference():
    assert pf.resolve_reference({"reference": "Patient/abc-123"}) == "abc-123"


def test_resolve_plain_string():
    assert pf.resolve_reference("urn:uuid:xyz") == "xyz"


def test_resolve_external_identifier_is_none():
    # identifier-style refs point outside the bundle -> out of scope
    ref = {"reference": "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|999"}
    assert pf.resolve_reference(ref) is None


def test_resolve_empty_is_none():
    assert pf.resolve_reference(None) is None
    assert pf.resolve_reference({}) is None


# --- parse_patient --------------------------------------------------------

def _patient():
    return {
        "resourceType": "Patient",
        "id": "pat-1",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory",
                            "valueCoding": {"code": "2106-3", "display": "White"}}]},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
             "extension": [{"url": "ombCategory",
                            "valueCoding": {"code": "2186-5", "display": "Not Hispanic or Latino"}}]},
        ],
        "name": [{"family": "Yost751", "given": ["Adrian111"]}],
        "gender": "female",
        "birthDate": "1989-01-27",
        "address": [{"city": "North Andover", "state": "Massachusetts"}],
    }


def test_parse_patient_core_fields():
    row = pf.parse_patient(_patient())
    assert row["patient_id"] == "pat-1"
    assert row["family_name"] == "Yost751"
    assert row["given_name"] == "Adrian111"
    assert row["gender"] == "female"
    assert row["birth_date"] == "1989-01-27"
    assert row["city"] == "North Andover"
    assert row["state"] == "Massachusetts"


def test_parse_patient_us_core_extensions():
    row = pf.parse_patient(_patient())
    assert row["race"] == "White"
    assert row["ethnicity"] == "Not Hispanic or Latino"


def test_parse_patient_missing_optionals_dont_crash():
    minimal = {"resourceType": "Patient", "id": "pat-2"}
    row = pf.parse_patient(minimal)
    assert row["patient_id"] == "pat-2"
    assert row["family_name"] is None
    assert row["race"] is None          # no extension -> None, not an error


# --- end-to-end over a written bundle ------------------------------------

def test_parse_bundles_reads_files(tmp_path):
    bundle = {"resourceType": "Bundle",
              "entry": [{"fullUrl": "urn:uuid:pat-1",
                         "resource": _patient()},
                        {"resource": {"resourceType": "Procedure", "id": "proc-1"}}]}
    (tmp_path / "b.json").write_text(json.dumps(bundle))
    tables = pf.parse_bundles(tmp_path)
    assert len(tables["patients"]) == 1          # Procedure ignored (out of scope)
    assert tables["patients"][0]["patient_id"] == "pat-1"


# --- deceased patients (kept in scope) -----------------------------------

def test_parse_patient_deceased_date():
    p = _patient()
    p["deceasedDateTime"] = "2010-01-01T11:16:32-05:00"
    assert pf.parse_patient(p)["deceased_date"] == "2010-01-01T11:16:32-05:00"


def test_parse_patient_living_has_no_deceased_date():
    assert pf.parse_patient(_patient())["deceased_date"] is None


# --- encounters -----------------------------------------------------------

def _encounter():
    return {
        "resourceType": "Encounter",
        "id": "enc-1",
        "status": "finished",
        "class": {"code": "AMB"},
        "type": [{"coding": [{"code": "162673000", "display": "General examination"}]}],
        "subject": {"reference": "urn:uuid:pat-1"},
        "period": {"start": "2007-03-23T16:12:06-04:00", "end": "2007-03-23T16:47:34-04:00"},
    }


def test_parse_encounter_fields_and_fk():
    row = pf.parse_encounter(_encounter())
    assert row["encounter_id"] == "enc-1"
    assert row["patient_id"] == "pat-1"          # reference resolved
    assert row["class"] == "AMB"
    assert row["type_code"] == "162673000"
    assert row["type_display"] == "General examination"
    assert row["start"] and row["end"]


def test_parse_encounter_missing_period_ok():
    e = _encounter(); del e["period"]
    row = pf.parse_encounter(e)
    assert row["start"] is None and row["end"] is None


# --- conditions -----------------------------------------------------------

def _condition():
    return {
        "resourceType": "Condition",
        "id": "cond-1",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"code": "44054006", "display": "Diabetes mellitus type 2"}]},
        "subject": {"reference": "urn:uuid:pat-1"},
        "encounter": {"reference": "urn:uuid:enc-1"},
        "onsetDateTime": "2010-05-01T00:00:00-04:00",
    }


def test_parse_condition_fields_and_fks():
    row = pf.parse_condition(_condition())
    assert row["condition_id"] == "cond-1"
    assert row["patient_id"] == "pat-1"
    assert row["encounter_id"] == "enc-1"
    assert row["code"] == "44054006"
    assert row["display"] == "Diabetes mellitus type 2"
    assert row["clinical_status"] == "active"


def test_parse_condition_without_encounter():
    c = _condition(); del c["encounter"]
    assert pf.parse_condition(c)["encounter_id"] is None   # optional FK -> None


# --- orphan handling ------------------------------------------------------

def test_child_with_unresolvable_patient_is_skipped(tmp_path):
    enc = _encounter()
    enc["subject"] = {"reference": "Practitioner?identifier=x|1"}  # unresolvable
    bundle = {"resourceType": "Bundle",
              "entry": [{"resource": _patient()}, {"resource": enc}]}
    (tmp_path / "b.json").write_text(json.dumps(bundle))
    tables = pf.parse_bundles(tmp_path)
    assert len(tables["patients"]) == 1
    assert len(tables["encounters"]) == 0        # orphan skipped, not loaded


# --- observations: value[x] + component explode ---------------------------

def _obs(**value):
    base = {
        "resourceType": "Observation",
        "id": "obs-1",
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"code": "8302-2", "display": "Body Height"}]},
        "subject": {"reference": "urn:uuid:pat-1"},
        "encounter": {"reference": "urn:uuid:enc-1"},
        "effectiveDateTime": "2020-01-01T00:00:00-05:00",
    }
    base.update(value)
    return base


def test_observation_quantity_one_row():
    row = pf.parse_observation(_obs(valueQuantity={"value": 168.8, "unit": "cm"}))
    assert isinstance(row, dict)
    assert row["value_type"] == "quantity"
    assert row["value_num"] == 168.8 and row["value_unit"] == "cm"
    assert row["patient_id"] == "pat-1" and row["encounter_id"] == "enc-1"
    assert row["parent_observation_id"] is None


def test_observation_codeable_uses_value_text():
    row = pf.parse_observation(_obs(
        valueCodeableConcept={"coding": [{"code": "8517006", "display": "Former smoker"}]}))
    assert row["value_type"] == "codeable"
    assert row["value_text"] == "Former smoker"
    assert row["value_num"] is None


def test_observation_component_explodes():
    panel = _obs()
    panel["code"] = {"coding": [{"code": "85354-9", "display": "Blood pressure panel"}]}
    panel["component"] = [
        {"code": {"coding": [{"display": "Systolic Blood Pressure"}]},
         "valueQuantity": {"value": 110, "unit": "mm[Hg]"}},
        {"code": {"coding": [{"display": "Diastolic Blood Pressure"}]},
         "valueQuantity": {"value": 76, "unit": "mm[Hg]"}},
    ]
    rows = pf.parse_observation(panel)
    assert isinstance(rows, list) and len(rows) == 2
    assert {r["observation_id"] for r in rows} == {"obs-1#0", "obs-1#1"}   # unique PKs
    assert all(r["parent_observation_id"] == "obs-1" for r in rows)        # grouped
    assert all(r["value_type"] == "component" for r in rows)
    assert rows[0]["display"] == "Systolic Blood Pressure" and rows[0]["value_num"] == 110


def test_observation_with_no_value():
    row = pf.parse_observation(_obs())
    assert row["value_type"] is None
    assert row["value_num"] is None and row["value_text"] is None
