# Persistence foundation (sub-project 1 of 4): design

Date: 2026-10-24. Status: approved in brainstorming, pending spec review.

## Context and goal

AutoGrade-RDF is a file-based prototype: questions, rubrics and gold triples are YAML, answers and human scores are CSV, and runs are JSON/TTL folders under `outputs/runs/`. The goal of the overall effort is a fully functional app that works as a polished, persistent demo and can also grade a real course, used by one lecturer on one machine.

The effort is split into four sub-projects, each with its own spec, plan and implementation:

1. **Persistence foundation** (this spec): SQLite + Oxigraph behind the existing `io`/`pipeline` seams, a one-time import, and the Semantic Web layer made visible. No new grading features.
2. **Courses and data entry**: Course → Assessment → Question, students per course, CSV/Excel import of answers and human scores, multipage Streamlit app.
3. **Question authoring**: in-app forms for question, reference answer, rubric and gold triples (ontology and `predicates.yaml` stay files).
4. **Grading, review and export**: grading an assessment in the Streamlit session with a progress bar (resumable per answer), ledger review with overrides, a `graded → reviewed` gate, and a student × question grade export.

Decisions that hold for all four: the database is the single source of truth after a one-time import; the app is local Streamlit; the score formulas, frozen parameters and Agent Rules in `PROTOTYPE_PLAN.md` are unchanged (corrected scores never feed `evaluate`); and the app must visibly show every Semantic Web concept of the research design (RDF, Turtle, OWL, SWRL/Pellet, SKOS, PROV-O, named graphs, SPARQL).

## Scope of sub-project 1

In scope:

- Remove the SAF dataset and its code paths.
- Add `db.py` + `schema.sql` (SQLite) and `kg.py` (Oxigraph) and `importer.py`.
- Move every reader and writer of `data/` and `outputs/runs/` onto the stores.
- Add a Knowledge Graph page, a Pellet before/after view and a visible SPARQL parity check to the existing app.

Out of scope (later sub-projects): course/assessment/student forms, CSV import UI, authoring forms, review gate, grade export, splitting the app into Streamlit multipage files.

## 1. SAF removal (first step)

The SAF subset is dropped; a better dataset will replace it later.

- Delete `data/external/saf/`, `data/questions/SAF_*`, `docs/gold_SAF_*_review.md`, `scripts/import_saf.py`, `tests/test_saf.py`.
- Remove `include_saf`, `--saf`, `--annotated-only` and `io.SAF_DIR` from `io`, `pipeline`, `cli`, `evaluate`, `app/` and tests. Remove the "Inggris (SAF)" filter in the ontology page.
- Keep: holistic `_total` scores (`io.TOTAL`), `language: en` rubrics, English extraction prompts, `lang: en` predicates in `config/predicates.yaml`, and the English ontology relations (`utilizes ≡ uses`, `has ⊥ lacks`, etc.). They are generic and a new dataset may be English.
- Record the removal in `docs/DECISIONS.md` and update `README.md`. Add a note at the top of `PROTOTYPE_PLAN.md` Section 2 pointing to this spec for the storage layout.

## 2. Data layout

### Location

Both stores live in `<project root>/db/` (added to `.gitignore`): `db/autograde.sqlite` and `db/kg/`. The environment variable `AUTOGRADE_DB_DIR` overrides the directory (tests use a temp dir).

### SQLite (records)

WAL mode, foreign keys on, schema version in `PRAGMA user_version`. Pipeline dicts and pydantic models are stored as JSON text columns, not normalized.

| Table | Columns | Notes |
|---|---|---|
| `course` | `id` PK, `code`, `name` | |
| `assessment` | `id` PK, `course_id` FK, `name` | |
| `question` | `id` PK (e.g. `Q1`), `assessment_id` FK, `prompt`, `reference_answer`, `rubric` JSON, `gold` JSON | `rubric` and `gold` hold the same dicts as today's `rubric.yaml`/`gold.yaml`, so `gold.validate` is unchanged |
| `student` | `id` PK, `course_id` FK, `external_id`, `name` | `UNIQUE(course_id, external_id)`; empty after import in this sub-project |
| `answer` | `id` PK (globally unique, e.g. `Q1_S01`), `question_id` FK, `student_id` FK NULL, `text`, `split` (`pilot`/`test`), `source` (`real`/`synthetic`), `annotation` JSON NULL | `annotation` replaces `data/annotations/*.yaml` |
| `human_score` | `answer_id` FK, `rater_id`, `criterion`, `score_0_100` | PK (`answer_id`, `rater_id`, `criterion`) |
| `run` | `id` PK, `mode`, `split`, `question`, `params` JSON, `params_frozen`, `reasoner`, `include_synthetic`, `created`, `finished` NULL, `evaluation_md` NULL | replaces `run.json` and `evaluation.md` |
| `result` | `run_id` FK, `answer_id` FK, `score`, `sentences`, `students`, `ledger`, `feedback`, `trace`, `extraction_log` (JSON), `ledger_corrected` NULL, `score_corrected` NULL | PK (`run_id`, `answer_id`). The row's existence means "this answer is done" |
| `override` | `id` PK, `answer_id` FK, `reference_id`, `status`, `by`, `date`, `reason` | replaces `data/human/overrides.yaml` |
| `evidence_audit` | `answer_id` FK + the columns of today's `evidence_audit.csv` | |

### Oxigraph (graphs)

One named graph per document:

| Named graph | Content | Replaces |
|---|---|---|
| `urn:ag:ontology` | `ontology/autograde.owl` | read directly from the file |
| `urn:ag:gold:<qid>` | `gold.to_graph(...)` output | `data/questions/<qid>/gold.ttl` |
| `urn:ag:run:<run_id>:<answer_id>:answer` | `ledger.answer_graph(...)` (student triples, sentences, PROV, reasoner input/output) | `answer.ttl` |
| `urn:ag:run:<run_id>:<answer_id>:ledger` | `ledger.to_graph(...)` | `ledger.ttl` |
| `urn:ag:run:<run_id>:<answer_id>:ledger_corrected` | corrected ledger graph | `ledger_corrected.ttl` |

`urn:ag:ontology` is refreshed by `kg.sync_ontology()` when the SHA-256 of `autograde.owl` differs from the hash stored in SQLite (a one-row `meta` table, key `ontology_sha256`). It runs on `db import` and on app start.

### What stays as files

`config/*.yaml` (including `frozen.yaml`), `config/predicates.yaml`, `ontology/` (Protégé edits it and Pellet loads the `.owl` file), `outputs/cache/` (LLM and embedding caches), `outputs/extract/` (debug output of `cli extract`), and `docs/gold_<qid>_review.md`.

## 3. Modules and interfaces

### New modules

**`src/autograde/schema.sql`**: the `CREATE TABLE` statements above plus `meta(key PRIMARY KEY, value)`.

**`src/autograde/db.py`** (stdlib `sqlite3`, no ORM):

- `db_dir()`: `AUTOGRADE_DB_DIR` or `io.ROOT / "db"`.
- `connect()`: opens `autograde.sqlite`, sets WAL and `foreign_keys`, applies `schema.sql` to a new file and sets `user_version`. On a version mismatch it raises: "database schema is version X, code expects Y; run `python -m autograde db import --replace`".
- Plain functions per table that return dicts, pydantic models or DataFrames with today's column names. At least: `is_empty()`, `questions()`, `question(qid)`, `answers(include_synthetic=False)`, `answer(answer_id)`, `human_scores(include_synthetic=False)`, `annotation(answer_id)`, `create_run(...)`, `finish_run(run_id)`, `runs(finished_only=True)`, `run(run_id)`, `save_result(run_id, answer_id, res)`, `result(run_id, answer_id)`, `result_ids(run_id)`, `save_corrected(run_id, answer_id, entries, score)`, `overrides(answer_id=None)`, `add_overrides(rows)`, `evidence_audit()`, `save_evaluation(run_id, md)`, `get_meta(key)`, `set_meta(key, value)`.

**`src/autograde/kg.py`** (`pyoxigraph`, pinned to the current release in `requirements.txt`):

- `store()`: context manager that opens `db/kg/` for one operation and closes it. If another process holds the lock, it retries for about 2 seconds and then raises: "the knowledge graph store is in use by another process (app or CLI); close it and retry".
- `gold_graph_name(qid)`, `answer_graph_name(run_id, answer_id, kind)` with `kind` in `answer`, `ledger`, `ledger_corrected`.
- `put_graph(name, rdflib_graph)`: replaces the named graph's contents.
- `get_graph(*names) -> rdflib.Graph`: union of the named graphs, namespaces bound with `io.bind_namespaces`.
- `graphs() -> list[dict]`: name, kind, question, run, answer, triple count.
- `query(sparql)`: read-only SPARQL over the whole dataset (default graph = union of named graphs); refuses `SERVICE` and any update, as the current console does.
- `sync_ontology()`: see Section 2.

**`src/autograde/importer.py`**:

- `import_files(replace=False)`: refuses a non-empty DB unless `replace=True`, in which case it deletes `db/` and rebuilds both stores.
- Loads `data/questions/Q1` (prompt, reference answer, rubric, gold validated with `gold.load`'s checks) into course "Contoh dek (synthetic)" with one assessment; `data/synthetic/answers.csv`, `data/synthetic/scores.csv` and `data/synthetic/annotations/*.yaml` with `source = synthetic`; and, when present, `data/answers/answers.csv`, `data/human/scores.csv`, `data/annotations/`, `data/human/overrides.yaml`, `data/human/evidence_audit.csv` with `source = real`.
- Validates everything (pydantic, `gold.validate`, unique answer ids) before writing anything.
- Builds `urn:ag:gold:<qid>` for each question and runs `kg.sync_ontology()`.
- Does not import `outputs/runs/` (those runs contain SAF results; re-running the demo regenerates them).

CLI: `python -m autograde db init` (create empty stores) and `python -m autograde db import [--replace]`.

`importer.py` is the only module that reads `data/` after this sub-project.

### Changed modules

| Module | Before | After |
|---|---|---|
| `io.load_answers`, `io.load_human_scores` | CSV files | `db.answers()`, `db.human_scores()`; same DataFrame columns; the `include_saf` parameter is removed |
| `io.annotation_path` | YAML path | removed; callers use `db.annotation(answer_id)` |
| `io.question_ids`, `io.question_dir` | folders | `db.questions()`; prompt and reference answer from `db.question(qid)` |
| `io.load_scores` | CSV path | kept only for `importer.py` |
| `gold.load(qid)` | `gold.yaml`, `rubric.yaml` | `db.question(qid)` JSON columns; same return value |
| `gold.build(qid)` | writes `gold.ttl` + review md | `kg.put_graph(gold_graph_name(qid), ...)` + review md |
| `extract.extract_gold(answer_id, ...)` | annotation YAML | annotation dict from `db.annotation` |
| `pipeline.Context.load` | builds `gold.ttl` if missing | builds the gold graph if missing from the store |
| `pipeline.run_answer(ctx, answer_id, text, mode, run_id, use_llm_feedback)` | `out_dir` with files | computation unchanged; writes the answer and ledger graphs, reads the ledger and gold graphs back for the SPARQL recompute, raises `ParityError` on mismatch, then `db.save_result` |
| `pipeline.run_split(...)` | `run.json`, `scores.csv` | `db.create_run` at start (or reuse an existing `run_id`), skip answers already in `db.result_ids(run_id)`, `db.finish_run` at end |
| `pipeline.completed_runs`, `runs_dir` | run folders | `db.runs(finished_only=True)`; `runs_dir` removed |
| `ledger.write` | JSON, CSV, TTL files | removed; the CSV export is dropped |
| `ledger.recompute_sparql(ledger_graph, gold_graph, lam)` | file paths | rdflib graphs |
| `cli recompute` | run folder | `kg.get_graph` + `db.result` |
| `cli override --run R [--file overrides.yaml]` | `overrides.yaml` | optional `--file` adds rows with `db.add_overrides`; applies `db.overrides()` and writes `ledger_corrected` graph + `db.save_corrected` |
| `cli audit-template` | writes `data/human/evidence_audit.csv` | writes the blank template to `outputs/reports/<run_id>/evidence_audit_template.csv`; the filled CSV comes back with the new `cli audit-import --file` |
| `evaluate` | run folder, CSVs, `evidence_audit.csv` | `db` + `kg`; saves the report with `db.save_evaluation` and prints it; metrics CSVs and figures go to `outputs/reports/<run_id>/` |
| `cli run` | always a new run | new `--run-id` option names or resumes a run |
| `calibrate` | CSVs | `db`; still writes `config/frozen.yaml` |
| `app/explorer.load_answer(run_id, answer_id)` | answer folder | `db.result` + `kg.get_graph` |
| `app/rdfviz` path helpers | file paths | graph names; `merged_graph` takes names and calls `kg.get_graph` |
| app "try one answer" | `outputs/ui/<answer_id>` | fixed run id `ui` (created on first use, never marked finished, excluded from evaluation) |

## 4. Semantic Web made visible

Every existing view (OWL class hierarchy, properties, predicate relations ≡/⊥, SWRL rules, reified gold graph, SKOS concept hierarchy, answer graph with PROV, alignment and σ, ledger, SPARQL console, Semantic Explorer, evaluation) keeps working, now reading from the stores. Each graph view shows a caption naming its source named graph (e.g. `urn:ag:gold:Q1`).

### New "Knowledge Graph" page

Added to the existing sidebar navigation.

- Table of named graphs from `kg.graphs()`: kind (ontology / gold / answer / ledger / ledger_corrected), question, run, answer, triple count, and a dataset total.
- Selecting a graph shows it as **Turtle** (syntax-highlighted, downloadable), as an **interactive graph** (`rdfviz`/vis-network), and as an **(s, p, o) table**.
- **SPARQL over the whole dataset** through `kg.query`, with `GRAPH ?g` support and these presets:
  - recompute one answer's score (Eq. 6) from its persisted ledger and gold graphs;
  - every `CONTRADICTED` ledger entry across all answers to a question;
  - student triples derived from a given sentence (`prov:wasDerivedFrom`);
  - concepts of a question with their `skos:broader` chains;
  - triple count per named graph.

### Pellet before/after view

A "Reasoning (Pellet)" view per graded answer, built from the stored answer graph (nothing is recomputed):

- **Before**: student and reference triple nodes, the asserted `ag:alignedSubject` / `ag:alignedObject` edges, `ag:negated`, and the relevant `ag:equivalentPredicate` / `ag:incompatibleWith` links.
- **After**: the same graph plus the inferred `ag:contradicts` edges drawn dashed red. Each edge is labelled with the SWRL rule that fired (1: incompatible predicate, not negated; 2: same predicate, negated; 3: equivalent predicate, negated). The label is derived in the view from the predicates and `ag:negated`; it is a display aid, not stored.

### Visible parity check

In the ledger view: "Python score = X · SPARQL score from the store = X ✓", with an expander showing the recompute query and its result row.

## 5. Error handling

- **Oxigraph lock**: retry for about 2 s, then the clear error in Section 3.
- **Partial writes**: per answer, graphs are written first and the `result` row last in one SQLite transaction. An answer counts as done only when its row exists; a re-run overwrites orphan graphs.
- **Parity failure**: `ParityError` stops the answer and no `result` row is written.
- **Import**: all inputs are validated before any write; a non-empty DB needs `--replace`.
- **Schema version**: checked on connect; a mismatch asks for a re-import. No migration framework.
- **Missing DB**: any command other than `db init`/`db import` on a missing or empty DB fails with "no database; run `python -m autograde db import`". The app shows the same message instead of a traceback.

## 6. Testing

- `tests/conftest.py` gains a session-scoped autouse fixture that sets `AUTOGRADE_DB_DIR` to a temp dir and runs `importer.import_files()`. All tests, including the worked example on Q1, run against real SQLite + Oxigraph stores built from the repo files.
- New `test_db.py`: round trip per table, non-empty guard, `user_version` mismatch error.
- New `test_kg.py`: `put_graph`/`get_graph` round trip, `query` refuses `SERVICE` and updates, lock retry error, `sync_ontology` only reloads on a hash change.
- New `test_importer.py`: Q1 plus 7 synthetic answers (`Q1_A07`, `Q1_A08`, `Q1_S01`–`Q1_S05`) imported, all `source = synthetic`; the stored gold graph is isomorphic to `gold.to_graph` output for Q1; invalid gold aborts with nothing written.
- `test_pipeline.py` gains a resume test: running the same `run_id` twice grades each answer once.
- Existing tests are updated for the new signatures (`run_answer(..., run_id)`, `recompute_sparql(graphs)`, `explorer.load_answer(run_id, answer_id)`); `test_saf.py` is deleted.
- A guard test greps `src/autograde/` (except `importer.py`) and `app/` for the old path helpers and literals: `question_dir`, `annotation_path`, `runs_dir`, `"data" /`, `"outputs" / "runs"`, `gold.ttl`, `ledger.ttl`, `answer.ttl`. (Turtle downloads built in memory are allowed.)

### Acceptance

1. `conda run -n semantic_web pytest` passes offline.
2. `python -m autograde db import` succeeds on a fresh checkout.
3. `python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback`, then `evaluate --run <id>`, `recompute`, and `override` all work against the DB.
4. `streamlit run app/streamlit_app.py` shows every existing page plus the Knowledge Graph page, the Pellet before/after view and the parity check, with no reads from `data/`.
