# Courses and data entry (sub-project 2 of 4): design

Date: 2026-10-24. Status: decisions made in brainstorming, pending spec review. Builds on the persistence foundation (`2026-10-24-persistence-foundation-design.md`, branch `persistence-foundation`).

## Goal

A lecturer can set up a real course entirely in the app: create a course and its assessments, add questions to an assessment, import the students' answers from the LMS export, and optionally import their own (human) scores. After this sub-project, grading a new course's answers works with the existing **Nilai Jawaban** page and `python -m autograde run`.

Decisions from brainstorming:

- **Questions**: until the authoring forms of sub-project 3 exist, a question is added by uploading its four files (`question.md`, `reference_answer.md`, `rubric.yaml`, `gold.yaml`). Validation is the importer's own.
- **LMS CSV**: any CSV is accepted through a column-mapping step. It handles both a wide export (one row per student, one column per question, as in Moodle's Responses report) and a long one (one row per answer).
- **CSV only**: no Excel support, so no new dependency.

## Scope

In scope:

- The app gets `st.navigation` with two sections: **Data** (new pages) and **Penilaian & Semantic Web** (the seven existing pages, unchanged). Nilai Jawaban stays the default page.
- A **Mata Kuliah** page: create courses and assessments, list them, upload a question into an assessment, and view a course's student roster.
- An **Impor Jawaban** page: map an LMS CSV to answers for an assessment's questions, preview, import. A second tab imports human scores the same way.
- Pure, tested functions in `importer.py` and `db.py`. The pages only collect input and call them.

Out of scope, later or skipped:

- Rename or delete for courses, assessments, questions, students or answers. Skipped for now; the database can always be rebuilt with `db import --replace` plus a re-import.
- Excel upload and a CLI for these imports.
- Course filtering on the existing pages: their question selectors keep listing every question (ids are globally unique).
- Replacing an already imported answer. Re-importing skips existing answers and reports them, because replacing would silently invalidate graded results (sub-project 4 decides how re-grading works).
- Authoring forms (sub-project 3), batch grading, review and export (sub-project 4).

No schema change: `course`, `assessment`, `student` and `answer.student_id` already exist (schema version stays 1).

## 1. Data rules

- **Answer id**: `<question_id>_<slug(external_id)>`, where `slug` replaces every character outside `[A-Za-z0-9_-]` with `-` (answer ids end up in IRIs). Two students whose ids slug to the same value fail the import with both ids named.
- **Student**: one row per `(course_id, external_id)`, created on first import. A later import fills in a missing name but never overwrites one.
- **Source and split**: imported answers are `source = real`. The split is chosen on the page (`test` by default; `pilot` only for answers meant for calibration), and the page says so in one line.
- **Blank answers** (empty, whitespace or `-`, Moodle's "no response") are skipped and counted.
- **Duplicates in the file** (the same student twice for one question, e.g. two Moodle attempts) fail the import and name the students. The lecturer filters the export in the LMS.
- **Existing answers** (an answer id already in the DB) are skipped and listed in the preview.
- **Human scores**: numbers in 0–100. The criteria offered are the question's rubric criteria plus `_total` (`io.TOTAL`, a holistic score). A score whose student has no answer to that question fails the import. An existing `(answer_id, rater_id, criterion)` score is replaced, since correcting your own scores is normal.
- **All-or-nothing**: every import validates the whole file first and writes in one SQLite transaction.

## 2. Modules

### `importer.py` (new functions; `read_questions` and `import_files` keep working)

- `validate_question(prompt, reference_answer, rubric, gold_raw) -> refs`: the per-question checks now inline in `read_questions` (predicates against the ontology, `gold.validate`), plus a non-empty prompt and reference answer and a `question_id` matching `[A-Za-z0-9_-]+`. `read_questions` calls it.
- `add_question(assessment_id, files: dict[str, str]) -> qid`: takes the four uploaded files' text by file name, parses the YAML (a YAML error becomes `ImportDataError` with the file name), takes the id from `rubric.yaml`'s `question_id`, refuses an id already in the DB, validates, then writes `db.add_question` and the `urn:ag:gold:<qid>` graph exactly as `import_files` does.
- `answers_from_table(df, id_col, name_cols, columns, split) -> (rows, report)`: `columns` maps `qid -> (answer_col, filter)`, where `filter` is `None` (wide) or `(question_col, value)` (long, keeping only rows whose `question_col` equals `value`). Each row is `{answer_id, question_id, external_id, name, text, split, source: "real"}`. `name_cols` are joined with a space (Moodle splits first and last name). `report` counts blanks and lists existing answer ids, which are left out of `rows`. Raises `ImportDataError` for duplicates, slug collisions and an empty `id_col` value.
- `scores_from_table(df, course_id, id_col, qid, columns, rater_id) -> DataFrame`: `columns` maps `criterion -> column`. Returns rows in `db.SCORE_COLUMNS`. Raises `ImportDataError` for non-numeric or out-of-range values and for students without an answer to `qid`.

### `db.py` (new functions)

- `courses()`, `assessments(course_id)`: lists of dicts.
- `questions(assessment_id=None)`: an optional filter on the existing function.
- `students(course_id)`: a DataFrame with `external_id`, `name` and the number of answers.
- `answer_ids(question_ids)`: a set, used for the "already imported" check.
- `import_course_answers(course_id, rows)`: one transaction. It upserts the students (filling a missing name), maps `external_id -> student.id`, then inserts the answers.
- `add_human_scores(df, replace=False)`: the existing function. `replace=True` uses `INSERT OR REPLACE`.

### `app/manage.py` (new): `page_courses()` and `page_import()`

**Mata Kuliah**
- A form to add a course (code, name) and, for a selected course, a form to add an assessment (name).
- A table of the selected course's assessments and their questions (id, prompt, number of answers).
- **Unggah soal**: an `st.file_uploader` that accepts several `.md`/`.yaml` files into the selected assessment, with a link to `data/questions/Q1` as the example format. The upload succeeds or shows the `ImportDataError` / `GoldError` text.
- **Mahasiswa**: the roster table.

**Impor Jawaban** (course and assessment selectors at the top)
- Tab **Jawaban**: upload a CSV (read with `pd.read_csv(dtype=str, keep_default_na=False)`, encoding `utf-8-sig` so Excel-saved CSVs and the BOM work). Choose the student id column, the name column(s) and the layout (wide or long). Wide: one answer column per question in the assessment, or "—" to skip. Long: one question column and one answer column, plus the value that marks each question (it defaults to the question id when that value occurs). Choose the split. Then a preview (the first rows of `rows` and the report) and an **Impor** button.
- Tab **Nilai dosen**: upload a CSV. Choose the question, the student id column, the rater id (default `D1`) and one column per criterion (or "—"). Then a preview and **Impor**.
- After a write, the app clears `st.cache_data` (the `answers_table` cache) and shows the counts.

### `app/streamlit_app.py`

Replace the sidebar radio with `st.navigation({"Data": [...], "Penilaian & Semantic Web": [...]})` using `st.Page(callable, title=...)`. Keep the sidebar caption. The DB guard at the top stays, so an empty DB still shows the "run `db import`" message. Courses can only be created after the demo import.

## 3. Error handling

- Every import shows `ImportDataError` / `GoldError` messages with `st.error`. Nothing is written on an error.
- A CSV that can't be parsed is reported with the parser's message.
- A course code or assessment name that already exists shows the SQLite `UNIQUE` failure as a plain message.

## 4. Testing

- `test_importer.py`:
  - `add_question` round trip, using Q1's files under a new id and changing `question_id` in both YAMLs. The gold graph should be in the store.
  - Duplicate id refused.
  - Bad gold refused with nothing written.
- `test_importer.py`, `answers_from_table`:
  - Wide and long fixtures give the same rows.
  - Blanks and `-` are skipped.
  - Duplicates and slug collisions raise.
  - Existing ids are reported, not returned.
  - Name columns are joined.
- `test_importer.py`, `scores_from_table`:
  - Range and type errors.
  - A student without an answer raises.
  - `_total` is accepted.
- `test_db.py`:
  - Courses, assessments and students round trip.
  - `import_course_answers` creates the students once and fills a missing name on a second import without overwriting it.
  - `add_human_scores(replace=True)` replaces.
- `test_app.py`:
  - The navigation is updated: pages are switched with `at.switch_page` instead of the sidebar radio.
  - The two new pages render.
  - An AppTest run creates a course and an assessment, uploads Q1's files under a new id, and imports a two-student wide CSV. The answers then appear in Nilai Jawaban's answer list.

### Acceptance

1. `conda run -n semantic_web pytest` passes offline.
2. In `streamlit run app/streamlit_app.py`, the full flow works without touching `data/`. A lecturer creates a course and an assessment, uploads a question, imports a Moodle-style wide CSV and a scores CSV, then grades one imported answer on Nilai Jawaban (`llm` mode, since imported answers have no annotation).
