"""Tests for the DQ decision logic (no database needed)."""

import dq_checks as dq


def _r(name, severity, violations):
    return {"name": name, "severity": severity,
            "violations": violations, "passed": violations == 0}


def test_all_clean_no_blocking():
    results = [_r("orphan_encounters", dq.ERROR, 0),
               _r("unexpected_gender", dq.WARN, 0)]
    assert dq.decide(results) == []


def test_error_failure_blocks():
    results = [_r("deceased_before_birth", dq.ERROR, 3),
               _r("unexpected_gender", dq.WARN, 0)]
    blocking = dq.decide(results)
    assert len(blocking) == 1 and blocking[0]["name"] == "deceased_before_birth"


def test_warning_failure_does_not_block():
    results = [_r("orphan_encounters", dq.ERROR, 0),
               _r("quantity_obs_missing_value", dq.WARN, 42)]
    assert dq.decide(results) == []          # warnings never block the pipeline


def test_checks_registry_is_wellformed():
    for severity, name, sql in dq.CHECKS:
        assert severity in (dq.ERROR, dq.WARN)
        assert isinstance(name, str) and name
        assert sql.strip().lower().startswith("select")
