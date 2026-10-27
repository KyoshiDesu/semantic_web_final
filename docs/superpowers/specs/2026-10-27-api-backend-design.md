# API backend (phase 2, part 1 of 4): design

Date: 2026-10-27. Status: decisions made in brainstorming, pending spec review. Builds on the four merged phase 1 sub-projects (`2026-10-24-*-design.md`).

## Phase 2

The app moves from Streamlit to an API with a plain-HTML frontend, becomes subject-agnostic, and gets a real dataset. Four parts, built in this order (the user's choice):

1. **API backend** (this spec).
2. **Frontend**: plain HTML/CSS/vanilla JS pages in `web/`, its own visual design, replacing Streamlit (deleted when it reaches parity).
3. **Dataset and universal template**: a public dataset found online, one import template (rubric file + answers CSV) that outside rubrics are fitted to, and an adapter for the chosen dataset. Prefer content-scored answers (ASAP-SAS, SciEntsBank, Mohler); writing-quality essay sets (ASAP-AES, PERSUADE) don't suit triple matching.
4. **Subject-agnostic key building**: the LLM drafts the gold key (concepts, `skos:broader`, triples per criterion) from a rubric and reference answer; the lecturer reviews and edits it.

## Goal

Every feature of the current Streamlit app, available as a local JSON API that a plain-HTML frontend can call, plus an OWL export that opens in Protégé for browsing, reasoning and querying.

Decisions from brainstorming:

- **Local only.** One lecturer, one machine, no login. "Production ready" means robust, tested and packaged, not hosted. SQLite and embedded Oxigraph stay.
- **One process, one command.** `python -m autograde serve` runs uvicorn on `127.0.0.1`, serving the API at `/api` and the frontend's files from `web/` at `/` (same origin: no CORS, no second server).
- **Frontend shape** (for part 2, but it sets this API's response formats): plain HTML with no build step, structure borrowed from the example the lecturer gave (top nav, a home page that names each Semantic Web piece, SPARQL templates, an "explore relationships" link on every answer), with an original visual design.
- **Grading runs in a background thread** inside the API process, with progress in a `job` table. Closing the browser no longer stops grading.
- **Research is read-only** in the API. Calibration, research runs and `evaluate` stay CLI commands; the API serves their results.
- **OWL export for Protégé**: browse, run the reasoner, query. No re-import of an edited ontology.

## Scope

In scope:

- A FastAPI package `src/autograde/api/` covering the class workflow, the Semantic Web views and read-only research.
- The `serve` CLI command and a placeholder `web/index.html`.
- Schema version 3 (`job` table) with an in-place upgrade.
- `owl_export.py` and its endpoint.
- Three thread-safety fixes in the core (Section 3).
- Moving `app/explorer.py` and `app/rdfviz.py` into `src/autograde/`.

Out of scope:

- The frontend pages (part 2) and deleting Streamlit.
- Hosting, accounts, Docker, a `--host` option.
- Delete or rename endpoints (as in phase 1), SPARQL update.
- Starting research runs, calibration or evaluation from the API.
- Re-importing an ontology edited in Protégé.
- More than one grading job at a time.

## 1. Architecture

`python -m autograde serve [--port 8000]` starts uvicorn bound to `127.0.0.1`. On startup the server opens the database, creating an empty one if none exists so a new install starts in the app; a `SchemaVersionError` stops the server with its message. It then calls `kg.sync_ontology()` and marks interrupted jobs (Section 3).

New package `src/autograde/api/`:

| Module | Job |
|---|---|
| `app.py` | App factory, startup, error mapping, security middleware, `web/` static mount |
| `schemas.py` | Pydantic request and response models (validation and the `/docs` page) |
| `jobs.py` | The grading thread, the job table access, the shared caches |
| `routes/courses.py` | Courses, assessments, students |
| `routes/questions.py` | Question CRUD, live validation preview, zip download, predicates |
| `routes/imports.py` | Answer and lecturer-score CSV upload with column mapping |
| `routes/grading.py` | Grading jobs, status table, review, corrections, CSV exports |
| `routes/semantic.py` | Ontology, named graphs, Turtle, SPARQL and its templates, gold views, single-answer try, answer views, OWL export |
| `routes/research.py` | Runs, evaluation reports, figures (read-only) |

Route handlers stay thin: they validate input with Pydantic and call the existing `db`, `kg`, `pipeline`, `grades`, `importer`, `authoring` and `gold` functions. They read nothing from `data/` (the `test_no_file_reads` guard covers the new modules).

`app/explorer.py` and `app/rdfviz.py` have no Streamlit code; they move to `src/autograde/explorer.py` and `src/autograde/rdfviz.py`, and the Streamlit pages import them from there. The vendored `vis-network.min.js` stays in `app/static/` until part 2 moves it to `web/`.

Graphs go out in the two forms a plain-JS page can draw: the existing `{nodes, edges, details}` JSON (from `explorer.build` and `rdfviz.vis_graph`, drawn with vis-network) and DOT text (concept, reified, alignment, Pellet before/after, class hierarchy, predicate relations; drawn by a vendored WebAssembly Graphviz in part 2). The SPARQL templates are the existing `ANSWER_QUERIES`, `RUN_QUERIES` and `KG_QUERIES`.

The CLI is unchanged apart from `serve`. Streamlit keeps working until part 2. Store access is unchanged: `kg` opens Oxigraph per call and waits up to 2 s for the lock, so API requests and the grading thread take turns as the app and the CLI do today.

## 2. Endpoints

All under `/api`. Tables (status, ledger, SPARQL results) are `{columns, rows}`. Named-graph names go in a `?name=` query parameter because URNs contain colons. Each group notes the Streamlit page it replaces.

**Courses** (Mata Kuliah)

- `GET /courses`, `POST /courses`
- `GET /courses/{id}/assessments`, `POST /courses/{id}/assessments`
- `GET /courses/{id}/students`

**Questions** (Editor Soal, Soal)

- `GET /assessments/{id}/questions`
- `GET /questions/{qid}`: prompt, reference answer, rubric, gold, and the editor tables (`authoring.to_tables`)
- `POST /questions`, `PUT /questions/{qid}`: save from the editor tables (`authoring.from_tables`, `importer.save_question`)
- `POST /questions/preview`: validate the tables without saving; returns the errors, concept DOT, reified DOT, Turtle and YAML
- `POST /assessments/{id}/questions/upload`: the four files, multipart
- `GET /questions/{qid}/files.zip`
- `GET /predicates?lang=`: dropdown values (`extract.for_language`)

**Imports** (Impor Jawaban). Stateless: the browser sends the file again with the mapping.

- `POST /imports/preview`: CSV in, columns and the first rows out
- `POST /courses/{id}/answers`: CSV + mapping; reports added and skipped (`importer.answers_from_table`, `db.import_course_answers`)
- `POST /courses/{id}/scores`: CSV + mapping for the lecturer's scores (`importer.scores_from_table`, `db.add_human_scores`)

**Grading** (Penilaian)

- `GET /assessments/{id}/status`: `grades.status_table` plus counts per status
- `POST /assessments/{id}/grading` `{which: "new" | "stale", llm_feedback: bool}`: starts a job (Section 3)
- `GET /jobs/{id}`, `POST /jobs/{id}/cancel`
- `POST /assessments/{id}/review/bulk`: approves `grades.bulk_approvable`
- `POST /results/{run}/{answer}/review`
- `POST /results/{run}/{answer}/corrections` `[{reference_id, status, reason}]`: `db.add_overrides`, then `pipeline.apply_corrections` (recompute and SPARQL parity check)
- `GET /assessments/{id}/exports/grades.csv?draft=` and `.../feedback.csv?draft=`: 409 while `grades.ready` is false and `draft` is off

**Semantic Web** (Ontologi, Soal, Nilai, SPARQL, Explorer, KG)

- `GET /ontology`: class DOT, properties table, predicate relations DOT, SWRL rules, OWL text
- `GET /graphs`, `GET /graphs/turtle?name=`, `GET /graphs/view?name=` (vis JSON)
- `POST /sparql` `{query, graphs?}`: over the given graphs (rdflib, `rdfviz.run_query`) or the whole store (`kg.query`); a table or Turtle
- `GET /sparql/templates?scope=answer|run|kg`
- `GET /questions/{qid}/gold`: concept DOT, reified DOT, Turtle of `urn:ag:gold:<qid>`
- `POST /questions/{qid}/try` `{answer_id? | text, mode: "gold" | "llm", llm_feedback}`: grades one stored or pasted answer synchronously in the UI run (`pipeline.run_answer`, `pipeline.ui_run`)
- `GET /results/{run}/{answer}`: score breakdown, SPARQL recompute evidence (query, rows, both scores), ledger, corrected ledger, feedback, sentences, student triples
- `GET /results/{run}/{answer}/views/{graph | alignment | reasoning}`
- `GET /questions/{qid}/explorer?run=&answers=`: `explorer.build` for one question and several answers
- `GET /export/owl?run=&answer=` (Section 4)

**Research** (read-only)

- `GET /runs`, `GET /runs/{id}` (params and evaluation report), `GET /runs/{id}/figures/{name}`

## 3. Grading jobs

### Schema version 3

```sql
CREATE TABLE job (id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessment(id),
                  run_id TEXT NOT NULL REFERENCES run(id), which TEXT NOT NULL CHECK (which IN ('new', 'stale')),
                  llm_feedback INTEGER NOT NULL, answer_ids TEXT NOT NULL, total INTEGER NOT NULL,
                  done INTEGER NOT NULL DEFAULT 0, current TEXT, failures TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'cancelled', 'interrupted')),
                  created TEXT NOT NULL, finished TEXT);
```

Added to `schema.sql` and as the version 2 → 3 step in `db.UPGRADES`.

### Flow

1. `POST /assessments/{id}/grading` gets the assessment's run (`pipeline.assessment_run`) and reads `grades.status_table`. It takes the *belum dinilai* answers for `new` and the *usang* answers for `stale`, as `grade_tab` does. An empty list is a 422.
2. If any job is `running`, the request gets 409 with that job's id. Only one job runs at a time across the app.
3. It writes the job row (`answer_ids` fixed at this point) and starts a daemon thread on `jobs.run_job(job_id)`.
4. `run_job` loops over the answers. Before each answer it checks the job's cancel flag (a `threading.Event` held in `jobs.py`). It calls `pipeline.grade_assessment_answer` unchanged, then writes `done` and `current`. An exception adds `{answer_id, error}` to `failures` and the loop continues.
5. At the end: `db.finish_run`, then status `done` (or `cancelled`) and `finished`. Cancelling lets the current answer finish. An exception outside the per-answer handling is logged and leaves the job `interrupted`, so a crashed thread never stays `running` and blocks new jobs.
6. On startup, every job still `running` becomes `interrupted`. Starting again recomputes the list from the status table, so graded answers are skipped.

`GET /jobs/{id}` returns the row; the frontend polls it about once a second.

### Process-wide caches

- **One shared `Embedder`**, passed as `cosine=` to every `Context.load`. The model loads once per server.
- **Question contexts keyed by `(qid, updated)`**, checked before every answer. A key edited mid-job takes effect on the next answer; without the check, answers graded after the edit would look up to date while using the old key.

### Thread-safety fixes in the core

The API is the first caller to use the core from several threads at once.

1. `reason.contradictions` shares one owlready2 `World` (`_pellet`) across calls. Two answers reasoned at once would see each other's individuals. A module-level lock serialises it.
2. `Embedder.vector` mutates its cache and rewrites the cache file. A lock covers the update and the save.
3. `io.save_json` writes in place, so a crash or a concurrent reader can see half a file. It writes to a temp file in the same folder and then calls `os.replace`.

SQLite needs no change: one connection per operation, WAL, the default busy timeout.

`POST /questions/{qid}/try` stays synchronous. It can run while a job grades, safely once these fixes are in.

## 4. OWL export

`GET /api/export/owl?run=<id>[&answer=<id>]` downloads `autograde-<run>[-<answer>].owl` (`application/rdf+xml`). An assessment's page passes its run, `assessment-<id>`; research runs work the same way. The scope is one run because student IRIs (`ans:<answer>_t<n>`) are unique within a run but repeat across runs. 404 for an unknown run or answer, or a run with no results.

New module `src/autograde/owl_export.py`: `build(run_id, answer_id=None) -> rdflib.Graph` and `rdfxml(run_id, answer_id=None) -> bytes`. The graph holds:

1. **The ontology, embedded** (`urn:ag:ontology`): classes, properties, predicate individuals with `equivalentPredicate` and `incompatibleWith`, and the SWRL rules. Not linked with `owl:imports`, which Protégé would try to fetch from `http://example.org/autograde/ontology`. Its `owl:Ontology` header is replaced by `http://example.org/autograde/export/<run>[/<answer>]` with an `rdfs:comment` naming the run and the answers.
2. **The gold graph** of every question with an exported answer.
3. **Each answer's graph**: student triples, sentences, `prov:wasDerivedFrom`, `negated`, and the `alignedSubject`/`alignedObject` pairs (the reasoner's input). Every `ag:contradicts` triple is removed, so the reasoner in Protégé derives them again.
4. **Each answer's effective ledger**: `ledger_corrected` if it exists, else `ledger`. Never both: they share entry IRIs and `status` is functional, so both together would be inconsistent.

Additions that exist only in the export (the knowledge graph is unchanged):

- **Declarations** for every term used but not declared in `autograde.owl`, at least `skos:Concept` (class) and `skos:broader` (object property), so Protégé reads the file as OWL 2 DL.
- **`rdfs:label`** on every reference triple, student triple and ledger entry, e.g. `"Tumbuhan menggunakan Cahaya"` (`feedback.triple_label`) and `"R4 · PARTIAL · 0.5"`.

README gets an "Open in Protégé" section: open the file, choose HermiT, *Start reasoner*, see the inferred `contradicts` on a student triple, and two DL queries (`LedgerEntry and status value Hilang`, and `ReferenceTriple and criterion value <one criterion>`).

## 5. Errors, security, packaging

### Errors

Every error body is `{error, message, details}`. One mapping in `app.py`:

| Cause | Status |
|---|---|
| Unknown course, assessment, question, run, answer, job | 404 |
| `GoldError`, `ImportDataError`, request validation, invalid tables or mapping | 422, all messages in `details` |
| `sqlite3.IntegrityError` (duplicate course code, question id), a job already running, an export not ready | 409 |
| `kg.KGBusyError` | 503 with `Retry-After: 2` |
| No `ANTHROPIC_API_KEY` for `/try` in LLM mode | 400 naming the variable |
| `pipeline.ParityError` and anything else | 500, traceback logged; nothing saved |

### Security

No login, because the server is local. Any website open in the browser can still reach it, so:

- Bound to `127.0.0.1`. No `--host` option.
- `TrustedHostMiddleware` allows only `localhost` and `127.0.0.1` (blocks DNS rebinding).
- Every non-GET request with an `Origin` header that isn't the server's own gets 403. Without this, any page could POST a form to the server and, for example, start a paid LLM grading job.
- Uploads: 10 MB per file; CSV decoded as `utf-8-sig`. The importer's existing validation stays the trust boundary.
- `GET /runs/{id}/figures/{name}` serves only names listed in that run's report folder.
- SPARQL stays read-only through `kg.query` (`SERVICE` refused, updates don't parse) and `rdfviz.run_query`.

### Packaging

- `fastapi` pinned in `requirements.txt` (uvicorn, starlette and python-multipart are already there).
- `python -m autograde serve [--port 8000]`. Job failures go to uvicorn's logger.
- README: the run command, an endpoint overview with a pointer to `/docs`, the Protégé section.

## 6. Testing

pytest with FastAPI's `TestClient`, on the session's temp database (`conftest.imported_db`).

- One test file per route module: the happy path and each error mapping that module uses.
- Jobs: `run_job` is called directly to grade, to record one failing answer, to cancel, and to check `interrupted` after a simulated restart. Offline, with annotated synthetic answers and `reasoner: sparql`. One test checks the start endpoint really runs the job in a thread and returns at once.
- Concurrency: two threads reasoning at the same time get the correct, separate contradiction sets (`pellet` marker). `save_json` leaves either the old or the new file, never a partial one.
- OWL export: reload the file with owlready2 and run Pellet and HermiT (`pellet` marker); the inferred `contradicts` equal the stored `trace.contradictions` for every answer. The file parses with rdflib, contains the SWRL rules, and has no `ag:contradicts`.
- Security: a foreign `Origin` on a POST gets 403, a foreign `Host` gets 400, a figure name outside the report folder gets 404.
- Every existing test keeps passing, including `test_app.py`, `test_explorer.py` and `test_rdfviz.py` after the module move.
