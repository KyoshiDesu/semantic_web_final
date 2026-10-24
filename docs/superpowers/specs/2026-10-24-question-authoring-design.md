# Question authoring (sub-project 3 of 4): design

Date: 2026-10-24. Status: decisions made in brainstorming, pending spec review. Builds on sub-project 2 (`2026-10-24-courses-and-import-design.md`, branch `courses-import`).

## Goal

A lecturer can write and edit a question entirely in the app: the question text, the reference answer, the rubric criteria, the concepts (aliases and the SKOS `broader` hierarchy) and the gold reference triples. While they type, they see the gold graph that will be stored. The ontology and `config/predicates.yaml` stay files.

Decisions from brainstorming:

- **Create and edit.** Any question can be edited. If it already has graded results, the page warns that saving makes them stale. The results are kept, and re-grading is sub-project 4's job. The question id cannot change.
- **Editable tables** (`st.data_editor`) for criteria, concepts and triples, with dropdowns for predicates, criteria and concepts, and one **Simpan** button.
- **Live preview and validation**: the concept graph, the reified RDF graph and the Turtle of the future `urn:ag:gold:<qid>`, plus the same validation errors that block saving, all updated on every edit.
- **The 4-file upload stays.** The editor adds a **download as files** button (a zip in the `data/questions/<qid>/` format), so questions can be backed up, moved, or put into git.

## Scope

In scope:

- A new **Editor Soal** page in the Data section.
- A new module `src/autograde/authoring.py` (tables ⇄ rubric/gold dicts, the files for download). `importer.py` gets a shared save path for both upload and editor.
- `db.update_question` and `db.result_count`.

Out of scope:

- Deleting questions, renaming question ids, and moving a question to another assessment.
- LLM drafting of gold triples.
- Editing the ontology or `predicates.yaml` (adding a predicate still means editing the files, as today).
- Re-grading after an edit (sub-project 4).
- Version history of a question. The download is the backup.

No schema change.

## 1. Page: Editor Soal

**Choosing what to edit** (at the top):

- **Soal baru**: pick a course and an assessment, then type a question id (`[A-Za-z0-9_-]+`, must not exist). An optional "start from a copy of" selector prefills the tables from an existing question. Otherwise the draft starts with one empty row per table.
- **Ubah soal**: pick an existing question. If `db.result_count(qid) > 0`, show a warning: "N graded results use this key; after saving they are stale until you re-grade."

**The form** (one draft per question, kept in `st.session_state` until saved or abandoned):

| Field | Widget | Notes |
|---|---|---|
| Question text | `text_area` | markdown |
| Reference answer | `text_area` | |
| Language | radio `id` / `en` | `rubric.language`; filters the predicate dropdown with `extract.for_language` |
| Criteria | `data_editor`: `id`, `description` | rows can be added and deleted |
| Concepts | `data_editor`: `concept`, `aliases`, `broader` | `aliases`: multiselect that accepts new entries; `broader`: multiselect over the concept names |
| Reference triples | `data_editor`: `id`, `s`, `p`, `o`, `criterion`, `weight` | `s`: multiselect over concepts (accepted subjects); `p`: select over the language's predicates (without `other`); `o`: select over concepts; `criterion`: select over criteria ids; `weight` > 0, default 1. An empty `id` gets the next free `R<n>` on save |
| Validated by | `text_input` | on save, `validated_on` = today if a name is given, else both `null` |

Dropdown options come from the tables above them as returned in the same run, so a concept added in the concepts table can be picked in the triples table right away.

**Live preview** (below the form, for each run):

- Build `(rubric, gold_raw)` with `authoring.from_tables(...)`, then run `importer.validate_question` on it.
- If validation fails: `st.error` with the full error list, and Simpan is disabled.
- If it succeeds: tabs for the **concept graph** (`rdfviz.gold_concept_dot`, with the SKOS hierarchy), the **reified RDF** (`rdfviz.gold_reified_dot`) and the **Turtle** of `gold.to_graph(...)`. The caption reads "named graph `urn:ag:gold:<qid>` after saving".
- An expander also shows the generated `rubric.yaml` and `gold.yaml`.

**Buttons:**
- **Simpan**: calls `importer.save_question(...)`, which creates or updates the question, then clears `st.cache_data` and `st.cache_resource` (the `pipeline.Context` per question is cached) and shows a success message.
- **Unduh berkas (.zip)**: `st.download_button` with `authoring.question_files(...)` zipped. It is available whenever validation passes, including before saving.

## 2. Modules

### `src/autograde/authoring.py` (new; pure functions, no Streamlit)

- `to_tables(q) -> dict`: a `db.question(qid)` dict becomes `{prompt, reference_answer, language, validated_by, criteria: DataFrame, concepts: DataFrame, triples: DataFrame}`.
- `empty_tables() -> dict`: the same shape with one blank row in each table.
- `from_tables(qid, prompt, reference_answer, language, criteria, concepts, triples, validated_by, base_gold=None) -> (rubric, gold_raw)`:
  - Drops fully blank rows and strips strings.
  - Turns NaN or `None` lists into `[]`.
  - Numbers the triples whose id is blank.
  - Keeps the keys of `base_gold` it doesn't manage (e.g. `drafted_by`), so an edit doesn't lose them.
  - Sets `validated_on`.
  - Validation is not done here.
- `question_files(qid, prompt, reference_answer, rubric, gold_raw) -> dict[str, str]`: the four files' text (`yaml.safe_dump(..., allow_unicode=True, sort_keys=False)`), accepted by `importer.add_question`.

### `importer.py`

- `save_question(qid, prompt, reference_answer, rubric, gold_raw, assessment_id=None)`. With `assessment_id` it creates a question and refuses an existing id; without one it updates an existing question. In both cases it runs `validate_question` first and writes nothing on an error, then writes the DB row and replaces the `urn:ag:gold:<qid>` graph.
- `add_question` (the upload) parses the files and then calls `save_question`. Its behaviour is unchanged.

### `db.py`

- `update_question(qid, prompt, reference_answer, rubric, gold)`.
- `result_count(qid)`: the number of `result` rows for the question, over all runs.

### App

- `app/manage.py` gets `page_editor()`.
- `streamlit_app.py` adds it to the Data section as **Editor Soal**.
- The Soal & Kunci page gets a one-line hint: "edit in Editor Soal".

## 3. Error handling

- Validation errors are shown live and block Simpan. An error raised at save time (e.g. the id was taken meanwhile) is shown with `st.error`, and nothing is written.
- A predicate in a saved gold key that the current `predicates.yaml` no longer offers stays in the dropdown with a "(tidak dikenal)" suffix, so it isn't silently dropped. Validation then reports it.
- Switching the question discards the unsaved draft of the previous one. A "Belum disimpan" marker shows when the draft differs from the stored question.

## 4. Testing

- `test_authoring.py`:
  - `to_tables` → `from_tables` on Q1 gives back Q1's rubric and gold.
  - `question_files` → `importer.add_question` under a new id round trips.
  - Blank rows are dropped and triple ids are numbered.
  - `drafted_by` is preserved, and `validated_on` is set only together with a name.
- `test_importer.py`:
  - `save_question` creates, then updates (the gold graph changes in the store).
  - Updating an unknown id or creating an existing one fails.
  - A failed validation writes nothing.
- `test_db.py`: `result_count`.
- `test_app.py`:
  - Editor Soal renders for a new and an existing question.
  - Editing a criterion description of a copy of Q1 and saving updates the DB.
  - The stale-results warning shows for a question with results.

### Acceptance

1. `conda run -n semantic_web pytest` passes offline.
2. In the app:
   - A lecturer creates a new question from scratch (two criteria, a few concepts with one `broader` link, three triples), watching the graph preview update.
   - They save it, see it on Soal & Kunci and in the Knowledge Graph page as `urn:ag:gold:<qid>`, and download it as a zip that `add_question` accepts.
