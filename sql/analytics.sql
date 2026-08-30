-- analytics.sql — questions a provider/payer would actually ask of this warehouse.
-- PostgreSQL dialect. Each query states the business question it answers.
-- Run individually, or: psql -d fhir_dw -f sql/analytics.sql

-- ===========================================================================
-- Q1. What are the most common clinical diagnoses (by number of patients)?
--     Filters to SNOMED "(disorder)" so social-determinant findings
--     (employment, education, etc.) don't inflate the disease counts.
-- ===========================================================================
SELECT display AS diagnosis,
       count(DISTINCT patient_id) AS patients
FROM conditions
WHERE display LIKE '%(disorder)%'
GROUP BY display
ORDER BY patients DESC
LIMIT 10;

-- ===========================================================================
-- Q2. How has encounter volume trended over time, by encounter type?
--     AMB = ambulatory, EMER = emergency, IMP = inpatient, HH = home health.
-- ===========================================================================
SELECT EXTRACT(YEAR FROM start_time)::int AS yr,
       class,
       count(*) AS encounters
FROM encounters
WHERE start_time >= '2015-01-01'
GROUP BY yr, class
ORDER BY yr, class;

-- ===========================================================================
-- Q3. Care intensity: how many encounters per patient, and who are the
--     highest-utilization patients? (A payer cost / case-management signal.)
-- ===========================================================================
SELECT round(avg(enc_count), 1) AS avg_encounters_per_patient,
       max(enc_count)           AS max_encounters,
       min(enc_count)           AS min_encounters
FROM (
    SELECT p.patient_id, count(e.encounter_id) AS enc_count
    FROM patients p
    LEFT JOIN encounters e USING (patient_id)
    GROUP BY p.patient_id
) per_patient;

-- Top 5 highest-utilization patients
SELECT p.given_name, p.family_name,
       count(e.encounter_id) AS encounters
FROM patients p
JOIN encounters e USING (patient_id)
GROUP BY p.patient_id, p.given_name, p.family_name
ORDER BY encounters DESC
LIMIT 5;

-- ===========================================================================
-- Q4. What is each patient's MOST RECENT body weight? (Latest-value-per-group
--     is the canonical warehouse pattern — a window function does it cleanly.)
--     LOINC 29463-7 = Body Weight.
-- ===========================================================================
WITH ranked AS (
    SELECT patient_id, effective, value_num, value_unit,
           ROW_NUMBER() OVER (PARTITION BY patient_id
                              ORDER BY effective DESC) AS rn
    FROM observations
    WHERE code = '29463-7' AND value_num IS NOT NULL
)
SELECT p.given_name, p.family_name,
       r.value_num AS latest_weight, r.value_unit,
       r.effective::date AS measured_on
FROM ranked r
JOIN patients p USING (patient_id)
WHERE r.rn = 1
ORDER BY latest_weight DESC
LIMIT 10;

-- ===========================================================================
-- Q5. Chronic-disease lens: for every patient diagnosed with hypertension,
--     what is their latest kidney function (eGFR)? Flags reduced function
--     (<60), which is how diabetic/hypertensive kidney decline is tracked.
--     LOINC 33914-3 = eGFR (MDRD).  (This is "Alden's story" as a query.)
-- ===========================================================================
WITH latest_egfr AS (
    SELECT patient_id, value_num AS egfr, effective::date AS measured_on,
           ROW_NUMBER() OVER (PARTITION BY patient_id
                              ORDER BY effective DESC) AS rn
    FROM observations
    WHERE code = '33914-3' AND value_num IS NOT NULL
),
hypertensive AS (
    SELECT DISTINCT patient_id
    FROM conditions
    WHERE display ILIKE '%hypertension%'
)
SELECT p.given_name, p.family_name,
       e.egfr AS latest_egfr, e.measured_on,
       CASE WHEN e.egfr < 60 THEN 'reduced' ELSE 'normal' END AS kidney_status
FROM hypertensive h
JOIN patients p     USING (patient_id)
LEFT JOIN latest_egfr e ON e.patient_id = h.patient_id AND e.rn = 1
ORDER BY e.egfr NULLS LAST;

-- ===========================================================================
-- Q6. Cohort demographics: patient counts, deceased share, and average age
--     (age at death for the deceased, current age for the living).
-- ===========================================================================
SELECT gender,
       count(*)                                            AS patients,
       count(*) FILTER (WHERE deceased_date IS NOT NULL)   AS deceased,
       round(avg(date_part('year',
             age(COALESCE(deceased_date::date, current_date), birth_date)))) AS avg_age
FROM patients
GROUP BY gender
ORDER BY patients DESC;
