# Grading, review and export (sub-project 4 of 4): design

Date: 2026-10-24. Status: decisions made in brainstorming, pending spec review. Builds on sub-project 3 (`2026-10-24-question-authoring-design.md`, branch `question-authoring`).

## Goal

A lecturer grades a whole assessment in the app, reviews the results, corrects ledger entries where the system was wrong, and exports the final grades and feedback for the LMS.

The flow is: **imported → graded → reviewed → exported**.

Decisions from brainstorming:

- **Hard gate with a draft export.** "Ekspor nilai final" is disabled until every answer in the assessment is graded, up to date and reviewed. A draft export, clearly labelled and carrying a status column, is always available.
- **Grades file**: one row per student with the ID, the name, one column per question (the final score, 0–100) and the mean over the assessment's questions.
- **Feedback file**: a second, long CSV with one row per student × question, holding the score, the feedback summary and the feedback claims, ready to paste into LMS comments.
- **Bulk approval**: one button marks every graded answer with no ⚑ entry (partial, needs review) and no contradiction as reviewed. Flagged answers are reviewed one by one.

Decisions carried over from the earlier specs: grading runs in the Streamlit session with a progress bar and is resumable per answer (no worker). Corrected scores never feed `evaluate`. The score formula and the Agent Rules are unchanged.

## Scope

In scope:

- **Schema version 2 with an in-place upgrade.** The database now holds courses entered in the app, which a `db import --replace` would destroy, so `connect()` upgrades version 1 to version 2 with `ALTER TABLE`.
- One **grading run per assessment**.
- A new **Penilaian** page with three tabs: Nilai, Tinjau, Ekspor.
- `pipeline.apply_corrections` (moved out of `cli override`) and a new module `grades.py` for the status table and the exports.

Out of scope:

- A background worker. The browser tab must stay open while grading; closing it stops grading, and the next click resumes.
- LMS-specific export formats. The files are plain CSV; the lecturer maps them in the LMS.
- Per-question points and a weighted total.
- Emailing feedback.
- Un-reviewing an answer or correcting it after review. Re-grading resets the review.

## 1. Data

### Schema version 2

| Table | New column | Meaning |
|---|---|---|
| `run` | `assessment_id INTEGER NULL REFERENCES assessment(id)` | set only for assessment grading runs |
| `question` | `updated TEXT NULL` | ISO timestamp; set by `add_question` and `update_question` |
| `result` | `graded TEXT NULL` | ISO timestamp; set by `save_result` |
| `result` | `reviewed TEXT NULL`, `reviewed_by TEXT NULL` | set by `mark_reviewed`; `save_result` (re-grade) leaves them NULL |

- `schema.sql` gets the columns for new databases. `SCHEMA_VERSION = 2`.
- `connect()` on a version 1 file runs the five `ALTER TABLE ... ADD COLUMN` statements and sets `user_version = 2` in one transaction. Any other mismatch raises the existing `SchemaVersionError`.
- Existing rows get NULL, which means "not stale" and "not reviewed".

### Grading run per assessment

- Run id `assessment-<id>`, with `mode = "auto"`, `split = "all"`, `question = "all"`, `include_synthetic = 1` and `assessment_id` set.
- It is created on first use and reused afterwards. `finish_run` is called after each pass, so the run shows up on Penjelajah Graf.
- **Mode `auto`**: each answer uses `gold` extraction when it has a triple annotation and `llm` otherwise. The extraction log already records which one was used.
- Research runs (`cli run`, `evaluate`) are unchanged. An assessment run is never evaluated automatically.

### Answer status (in the assessment's run)

| Status | Rule |
|---|---|
| `belum dinilai` | no result row |
| `usang` | `result.graded < question.updated` (the key changed after grading) |
| `dinilai` | graded, up to date, not reviewed |
| `ditinjau` | `reviewed` is set and the answer is not stale |

The **final score** of an answer is `score_corrected` if present, else `score`.

## 2. Modules

### `db.py`

- The v1 → v2 upgrade in `connect()`.
- `create_run(..., assessment_id=None)`.
- `add_question` and `update_question` set `updated`, and `save_result` sets `graded`.
- `assessment_answers(assessment_id) -> DataFrame` with `answer_id, question_id, external_id, name, text, source, annotated`. For answers without a student (demo data), `external_id` is the answer id.
- `results(run_id) -> dict[answer_id, result dict]`: all results of a run in one query, with `graded`, `reviewed` and `reviewed_by`.
- `mark_reviewed(run_id, answer_ids, by)`.
- `question_updated(qids) -> dict`.

### `pipeline.py`

- `assessment_run(assessment_id) -> run_id`: creates or returns `assessment-<id>`.
- `grade_assessment_answer(run_id, row, contexts, use_llm_feedback)`:
  - Picks the mode (auto) and calls `run_answer`.
  - Calls `apply_corrections(run_id, answer_id)`, so earlier lecturer corrections on the same reference triples carry over to the new result.
  - `contexts` caches `Context` per question.
- `apply_corrections(run_id, answer_id) -> (score, skipped)`:
  - The body of today's `cli override` loop: it applies `db.overrides(answer_id)`, writes the `ledger_corrected` graph, checks SPARQL parity and calls `db.save_corrected`.
  - Overrides for reference triples that are no longer in the ledger (the key changed) are skipped and returned, instead of raising.
  - `cli override` calls it.

### `grades.py` (new)

- `status_table(assessment_id) -> DataFrame`: one row per answer with `answer_id, question_id, external_id, name, source, status, score, final, flagged` (the number of ⚑ entries), `contradictions` and `reviewed_by`. It is computed from `assessment_answers`, `results` and `question_updated`.
- `bulk_approvable(table)`: the answer ids with status `dinilai`, `flagged == 0` and `contradictions == 0`.
- `ready(table)`: True when every row is `ditinjau`.
- `grades_csv(table, qids, draft)`:
  - One row per student: the `external_id`, `name`, one column per question id (final score, 1 decimal) and `rata_rata`.
  - The mean is over all the assessment's questions. A question the student did not answer counts as 0, and its cell is left blank.
  - A draft adds a `status` column per student (e.g. `3/5 ditinjau`) and starts with the comment line `# DRAF — belum semua jawaban ditinjau`.
- `feedback_csv(table, run_id)`: one row per answered student × question, with `external_id, name, question_id, nilai, ringkasan, umpan_balik` (the claims joined with newlines).

### App: `app/grading.py` (new) → `page_grading()`

The page is registered as **Penilaian** in a new navigation section, "Penilaian Kelas", between Data and Penilaian & Semantic Web. At the top: course and assessment selectors, metrics (answers, graded, stale, reviewed) and the status table. A caption notes it when the assessment contains synthetic answers (Agent Rule 4).

**Nilai tab**
- Buttons: "Nilai N jawaban yang belum dinilai" and "Nilai ulang M jawaban usang".
- A "Umpan balik dari LLM" checkbox, and a note that answers without annotations need an API key.
- Grading loops in the session with `st.progress`. Each answer is graded on its own. A failure (no API key, `ParityError`) is collected and shown afterwards; the answer stays ungraded and is retried on the next click.

**Tinjau tab**
- "Nama peninjau" (required, kept in the session).
- **Bulk approval**: "Setujui K jawaban tanpa ⚑ dan tanpa kontradiksi".
- **Single answer**: a selector over the answers that are graded but not reviewed (unflagged ones last). It shows:
  - the answer text;
  - the system and final scores, and "SPARQL = X ✓" from the stored `sparql_score`;
  - the ledger as a `data_editor` with an editable `status` (select over MATCHED/PARTIAL/MISSING/CONTRADICTED) and `alasan` (reason). The other columns (reference triple, criterion, weight, σ, evidence sentences) are read-only.
- **Simpan koreksi** adds an override for each row whose status changed (a reason is required) and calls `apply_corrections`. **Tandai ditinjau** marks the answer reviewed.
- Expanders show the Turtle of the answer's `ledger` / `ledger_corrected` named graphs and the feedback.
- A caption points to Penjelajah Graf (run `assessment-<id>`) for the full graph views.

**Ekspor tab**
- **Ekspor nilai final** (grades CSV and feedback CSV) is enabled only when `ready(table)`; otherwise a caption says what is missing.
- **Ekspor draf** is always available.
- Files are named `<course code>_<assessment>_nilai[_draf].csv` and `..._umpan_balik[_draf].csv`, encoded `utf-8-sig` so Excel opens them correctly.

## 3. Error handling

- **Per-answer failures while grading** are collected, not fatal. Nothing is written for a failed answer (`run_answer` writes the result row last).
- **A schema upgrade failure** rolls back and raises with the SQLite message. The file stays at version 1.
- **A correction without a reason**, or one with no reviewer name, shows `st.error` and writes nothing.
- **A re-grade** clears the review and the stored corrected score (as `save_result` does today), then re-applies the answer's overrides.

## 4. Testing

- `test_db.py`:
  - A v1 database (columns dropped, `user_version = 1`) is upgraded on connect.
  - `updated`, `graded` and `mark_reviewed` behave as described.
  - `assessment_answers` falls back to the answer id when there is no student.
- `test_pipeline.py`:
  - `assessment_run` is idempotent.
  - `grade_assessment_answer` in auto mode on the synthetic Q1 answers uses gold, and re-applies an existing override.
  - `apply_corrections` skips an override for an unknown reference.
- `test_grades.py`:
  - The status transitions (ungraded → graded → stale after `update_question` → re-graded → reviewed).
  - `bulk_approvable`.
  - The grades CSV values, blanks, mean and draft marker.
  - The feedback CSV rows.
- `test_cli.py`: `override` still works through `apply_corrections`.
- `test_app.py`: on the DEMO assessment (7 synthetic annotated answers, offline):
  - Grade all, then bulk approve.
  - Correct one flagged answer and mark it reviewed.
  - Final export is enabled only at the end, and the CSV has one row per answer key.

### Acceptance

1. `conda run -n semantic_web pytest` passes offline.
2. In the app, on the DEMO assessment, a lecturer:
   - grades all answers with a progress bar;
   - bulk-approves the unflagged ones;
   - corrects Q1_A08's contradiction and approves it;
   - downloads the final grades and feedback CSVs;
   - edits Q1's key on Editor Soal and sees the answers become `usang`, which blocks the final export until they are re-graded and reviewed.
