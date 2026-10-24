# Question authoring: implementation plan

Spec: `docs/superpowers/specs/2026-10-24-question-authoring-design.md`. Branch `question-authoring` (from `courses-import`). Run tests with `conda run -n semantic_web pytest`. Each task ends with its tests passing and one commit.

## Task 0: data_editor spike

In a scratch AppTest, check that `st.data_editor` with a `key` keeps the user's edits when the options of its `SelectboxColumn` / `MultiselectColumn` change between reruns. If it doesn't, keep the column options stable and rely on validation.

## Task 1: db and importer save path

- `db.update_question` and `db.result_count`.
- `importer.save_question(qid, prompt, ref, rubric, gold_raw, assessment_id=None)`. `add_question` calls it.

Tests:
- Create, then update (the gold graph changes).
- Unknown and duplicate ids fail.
- An invalid key writes nothing.
- `result_count`.

## Task 2: authoring.py

`to_tables`, `empty_tables`, `from_tables` and `question_files`.

Tests:
- The Q1 round trip.
- `question_files` → `add_question`.
- Blank rows are dropped and ids numbered.
- `drafted_by` is kept, and `validated_on` is set only with a name.

## Task 3: Editor Soal page

- `manage.page_editor()`, registered in the navigation.
- A hint on Soal & Kunci.

AppTest:
- New question from a copy of Q1: edit a description, save, check the DB.
- Editing an existing question with results shows the stale warning.

## Task 4: docs and memory

- README paragraph.
- Memory status.
