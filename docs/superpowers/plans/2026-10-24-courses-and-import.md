# Courses and data entry: implementation plan

Spec: `docs/superpowers/specs/2026-10-24-courses-and-import-design.md`. Branch `courses-import` (from `persistence-foundation`). Run tests with `conda run -n semantic_web pytest`.

Each task ends with its tests passing and one commit.

## Task 1: db functions

`src/autograde/db.py`:
- `courses()`, `assessments(course_id)`: lists of dicts.
- `questions(assessment_id=None)`.
- `students(course_id)`: DataFrame `external_id, name, answers`.
- `answer_ids(question_ids)`: set.
- `import_course_answers(course_id, rows)`: one transaction. It upserts the students with `ON CONFLICT(course_id, external_id) DO UPDATE SET name = COALESCE(student.name, excluded.name)`, then inserts the answers with `student_id`.
- `add_human_scores(df, replace=False)`.

Tests in `tests/test_db.py`:
- Courses, assessments and students round trip.
- A second import fills a missing name and keeps an existing one.
- Scores are replaced when `replace=True`.

## Task 2: question upload

`src/autograde/importer.py`:
- Extract `validate_question(prompt, reference_answer, rubric, gold_raw)` from `read_questions`. It checks the id pattern, non-empty texts, predicates and `gold.validate`.
- Add `QUESTION_FILES` and `add_question(assessment_id, files)`. It parses the YAML, refuses an existing id, validates, then writes `db.add_question` and the gold graph.

Tests:
- Q1's files with the id rewritten to `Q1B` round trip, and the gold graph is stored.
- An existing id is refused.
- A bad predicate raises `GoldError` and nothing is written.
- A missing file or a YAML error raises `ImportDataError`.

## Task 3: CSV mapping

`src/autograde/importer.py`:
- `slug(s)`.
- `answers_from_table(df, course_id, id_col, name_cols, columns, split)`, which returns `(rows, report)`.
- `scores_from_table(df, course_id, id_col, qid, columns, rater_id)`.

Tests (inline DataFrames):
- A wide table and the equivalent long table give the same rows.
- Blank answers and `-` are skipped.
- Duplicates and slug collisions raise.
- Existing ids are reported.
- Name columns are joined.
- Scores: values outside 0–100 and non-numeric values raise, a student without an answer raises, and `_total` is accepted.

## Task 4: app pages

- New `app/manage.py` with `page_courses()` and `page_import()`.
- In `app/streamlit_app.py`, replace the sidebar radio with `st.navigation`. Pages are `st.Page(fn, title=..., url_path=...)` in the sections "Data" and "Penilaian & Semantic Web", with Nilai Jawaban as the default.
- After a write, clear `st.cache_data`.

Tests in `tests/test_app.py`:
- Page switching uses `at.switch_page`. If AppTest can't switch to callable pages, fall back to the `url_path`.
- The new pages render.
- The end-to-end flow: course → assessment → upload Q1 as `Q1B` → import a two-student wide CSV. The answers then show up in Nilai Jawaban (unannotated filter off).

## Task 5: docs

- README: the new pages and the CSV mapping, in one short section.
- Update the memory status.
