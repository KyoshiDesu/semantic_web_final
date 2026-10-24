# Grading, review and export: implementation plan

Spec: `docs/superpowers/specs/2026-10-24-grading-review-export-design.md`. Branch `grading-review` (from `question-authoring`). Run tests with `conda run -n semantic_web pytest`. Each task ends with its tests passing and one commit.

## Task 1: schema v2 and db

- `schema.sql`: the new columns. `SCHEMA_VERSION = 2`. `connect()` upgrades v1 to v2 in one transaction.
- `create_run(..., assessment_id=None)`.
- `updated` set in `add_question` and `update_question`; `graded` set in `save_result`.
- `assessment_answers`, `results`, `mark_reviewed` and `question_updated`.

Tests: the v1 upgrade (drop the columns, set `user_version = 1`), timestamps, review marks, and the student fallback.

## Task 2: pipeline

- `apply_corrections` (moved out of `cli override`, skipping unknown references). `cli override` calls it.
- `assessment_run` and `grade_assessment_answer` (auto mode, re-applies overrides).

Tests: the idempotent run, auto mode on the synthetic answers using gold, an override re-applied after a re-grade, an unknown reference skipped, and the existing CLI override test.

## Task 3: grades.py

`status_table`, `bulk_approvable`, `ready`, `grades_csv` and `feedback_csv`.

Tests:
- Status transitions, including stale after `update_question`.
- Bulk approval.
- CSV values, blanks, the mean and the draft marker.

## Task 4: Penilaian page

`app/grading.py` with `page_grading()` (tabs Nilai, Tinjau, Ekspor), registered under "Penilaian Kelas".

AppTest on DEMO:
- Grade all, then bulk approve.
- Correct Q1_A08, then mark it reviewed.
- The final export is enabled.

## Task 5: docs and memory

- README paragraph.
- `PROTOTYPE_PLAN` / `DECISIONS` note on the schema upgrade, if needed.
- Memory status.
