"""dq_checks.py — data-quality gates for the FHIR warehouse.

Runs a battery of SQL checks after load. Each check counts violating rows;
a check passes when that count is 0.

Two severities:
  - "error" checks BLOCK the pipeline (non-zero exit) — impossibilities /
    integrity breaks that must never ship.
  - "warn" checks report but don't block — plausibility signals worth seeing.

Philosophy: a silent bad load is worse than a failed one. See DECISIONS #018.

Run:  python src/dq_checks.py
"""

import logging

from load_postgres import connect   # reuse the same env-driven connection

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("dq_checks")

ERROR = "error"
WARN = "warn"

# Each check: violating-row count SQL. Passes when the count is 0.
CHECKS = [
    # --- structural integrity (should be guaranteed by schema; guard anyway) ---
    (ERROR, "orphan_encounters",
     "SELECT count(*) FROM encounters e "
     "LEFT JOIN patients p USING (patient_id) WHERE p.patient_id IS NULL"),
    (ERROR, "orphan_conditions",
     "SELECT count(*) FROM conditions c "
     "LEFT JOIN patients p USING (patient_id) WHERE p.patient_id IS NULL"),
    (ERROR, "orphan_observations",
     "SELECT count(*) FROM observations o "
     "LEFT JOIN patients p USING (patient_id) WHERE p.patient_id IS NULL"),
    (ERROR, "patients_table_not_empty",
     "SELECT CASE WHEN count(*) = 0 THEN 1 ELSE 0 END FROM patients"),

    # --- data impossibilities (real errors) ---
    (ERROR, "deceased_before_birth",
     "SELECT count(*) FROM patients "
     "WHERE deceased_date IS NOT NULL AND deceased_date < birth_date"),
    (ERROR, "birth_date_in_future",
     "SELECT count(*) FROM patients WHERE birth_date > current_date"),

    # --- plausibility / quality signals (warnings) ---
    (WARN, "encounter_negative_interval",
     "SELECT count(*) FROM encounters "
     "WHERE start_time IS NOT NULL AND end_time IS NOT NULL AND end_time < start_time"),
    (WARN, "quantity_obs_missing_value",
     "SELECT count(*) FROM observations "
     "WHERE value_type = 'quantity' AND value_num IS NULL"),
    (WARN, "condition_onset_before_birth",
     "SELECT count(*) FROM conditions c JOIN patients p USING (patient_id) "
     "WHERE c.onset_date IS NOT NULL AND c.onset_date < p.birth_date"),
    (WARN, "unexpected_gender",
     "SELECT count(*) FROM patients "
     "WHERE gender IS NOT NULL AND gender NOT IN ('male','female','other','unknown')"),
]


def run_checks(cur):
    """Execute every check; return a list of result dicts."""
    results = []
    for severity, name, sql in CHECKS:
        cur.execute(sql)
        violations = cur.fetchone()[0]
        results.append({"name": name, "severity": severity,
                        "violations": violations, "passed": violations == 0})
    return results


def decide(results):
    """Return the list of BLOCKING failures (error-severity checks that failed).
    Pure function -> unit-testable without a database."""
    return [r for r in results if r["severity"] == ERROR and not r["passed"]]


def report(results):
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        log.info("[%s] %-5s %-28s violations=%d",
                 status, r["severity"], r["name"], r["violations"])


def main():
    conn = connect()
    try:
        with conn.cursor() as cur:
            results = run_checks(cur)
    finally:
        conn.close()

    report(results)
    blocking = decide(results)
    if blocking:
        names = ", ".join(r["name"] for r in blocking)
        log.error("DQ FAILED — blocking checks: %s", names)
        raise SystemExit(1)
    warns = [r for r in results if r["severity"] == WARN and not r["passed"]]
    if warns:
        log.warning("DQ passed with %d warning(s)", len(warns))
    else:
        log.info("DQ passed — all checks clean")


if __name__ == "__main__":
    main()
