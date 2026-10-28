# API Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every feature of the Streamlit app as a local FastAPI JSON API (`/api`) plus a static `web/` mount, with background grading jobs and an OWL export that Protégé can browse, reason over and query.

**Architecture:** A thin `src/autograde/api/` package wraps the existing core (`db`, `kg`, `pipeline`, `grades`, `importer`, `authoring`, `gold`). Grading runs in one daemon thread at a time with progress in a new `job` table (schema v3). Two Streamlit-free view modules move from `app/` into the package, a new core module `owl_export.py` builds the Protégé file, and three thread-safety fixes make the core safe to call from several threads.

**Tech Stack:** Python 3.12 (conda env `semantic_web`), FastAPI + uvicorn + starlette, pydantic 2, rdflib, pyoxigraph, owlready2 (Pellet/HermiT), pandas, pytest + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-10-27-api-backend-design.md`

## Global Constraints

- Run every command from the repo root `/Users/koizumirisa/Documents/Projects/semantic_web_final`, through conda: `conda run -n semantic_web <command>`. Never a `.venv`.
- Work on branch `api-backend` (it exists and holds the spec).
- The server binds `127.0.0.1` only. No `--host` option.
- Every error body is `{"error": <code>, "message": <text>, "details": [<text>, ...]}`.
- Uploads: at most 10 MB per file (413 above that); CSV read as `utf-8-sig` with the separator sniffed.
- One grading job at a time across the app.
- No delete or rename endpoints, no SPARQL update.
- Route handlers stay thin and read nothing from `data/` (`tests/test_no_file_reads.py` guards it).
- Streamlit (`streamlit run app/streamlit_app.py`) and every CLI command keep working; the whole `pytest` suite stays green.
- Match the surrounding code: module docstrings, one-line comments only for a *why*, no type hints except where FastAPI needs them (path, query and body parameters), English messages. Status labels from the core stay Indonesian (`belum dinilai`, `usang`, `dinilai`, `ditinjau`).
- Commit messages follow the repo style (sentence case, imperative, no `feat:` prefix) and end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Indonesian-locale CSV exports** (`;` separator, UTF-8 BOM): preview and import must read the right columns. Test in Task 7.
- **A mapping that names a column the CSV doesn't have**: 422 naming the column, never a 500 `KeyError`. Test in Task 7.
- **Empty cells in tables** (demo answers have no student name): JSON `null`, never `NaN` or a 500. Test in Task 8.
- **A typo in a SPARQL query**: 422 carrying the parser's message, not a 500. Test in Task 9.
- **The server stops mid-job**: the next start shows the job `interrupted`, and starting again grades only the answers still left. Test in Task 8.

## Small additions to the spec

These came up while mapping the Streamlit pages onto endpoints. Each is a few lines, and the plan includes them:

- `src/autograde/api/deps.py`: the "unknown id → 404" lookups, the upload size check and `is_stale`, shared by every route module.
- `GET /questions` (every question, for pages that pick any question) and `GET /questions/{qid}/answers` (the stored answers the Nilai demo picks from, with lecturer totals).
- `?dry_run=true` on the two CSV imports: it returns the report without writing, which is the "check, then import" step the Streamlit page has.
- 413 for an upload over 10 MB.
- An answer view that the current key can no longer draw (the key gained a reference triple after grading) returns 409 "grade it again" instead of a 500.
- `importer.QuestionExistsError` (a subclass of `ImportDataError`), so a duplicate question id is a 409 whether it comes from the editor or from a file upload.

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `src/autograde/io.py` | modify | `save_json` becomes atomic |
| `src/autograde/normalize.py` | modify | `Embedder` lock |
| `src/autograde/reason.py` | modify | Pellet lock |
| `src/autograde/explorer.py`, `src/autograde/rdfviz.py` | move from `app/` | View builders (JSON graphs, DOT, SPARQL templates) |
| `src/autograde/schema.sql`, `src/autograde/db.py` | modify | Schema v3 `job` table; job, course and assessment functions |
| `src/autograde/owl_export.py` | create | One run (or answer) as a self-contained OWL file |
| `src/autograde/importer.py` | modify | `QuestionExistsError` |
| `src/autograde/cli.py` | modify | `serve` command |
| `src/autograde/api/__init__.py` | create | Package docstring |
| `src/autograde/api/app.py` | create | App factory, startup, error mapping, security, `web/` mount |
| `src/autograde/api/deps.py` | create | 404 lookups, upload limit, `is_stale` |
| `src/autograde/api/schemas.py` | create | Request models and `table(df)` |
| `src/autograde/api/jobs.py` | create | Grading thread, job lifecycle, shared caches |
| `src/autograde/api/routes/__init__.py` | create | Empty |
| `src/autograde/api/routes/courses.py` | create | Courses, assessments, students |
| `src/autograde/api/routes/questions.py` | create | Question CRUD, preview, upload, zip, predicates |
| `src/autograde/api/routes/imports.py` | create | CSV preview and imports |
| `src/autograde/api/routes/grading.py` | create | Jobs, status, review, corrections, exports |
| `src/autograde/api/routes/semantic.py` | create | Ontology, graphs, SPARQL, gold, try, results, views, explorer, OWL export |
| `src/autograde/api/routes/research.py` | create | Runs, evaluation, figures |
| `web/index.html` | create | Placeholder page until part 2 |
| `app/streamlit_app.py`, `app/manage.py` | modify | Import the moved modules |
| `requirements.txt` | modify | Pin `fastapi` |
| `README.md` | modify | `serve`, the API overview, "Open in Protégé" |
| `tests/conftest.py` | modify | `client` fixture |
| `tests/test_io.py`, `tests/test_owl_export.py`, `tests/test_api_*.py` | create | New tests |
| `tests/test_normalize.py`, `tests/test_reason.py`, `tests/test_db.py`, `tests/test_explorer.py`, `tests/test_rdfviz.py`, `tests/test_pipeline.py`, `tests/test_no_file_reads.py` | modify | New cases and import paths |

---

### Task 1: Thread-safety fixes in the core

The API is the first caller that uses the core from several threads at once. Three shared things break under that: the JSON cache writes, the embedding cache, and the single owlready2 `World` behind Pellet.

**Files:**
- Modify: `src/autograde/io.py` (imports at the top; `save_json` near line 48)
- Modify: `src/autograde/normalize.py` (`Embedder`, lines 45-61)
- Modify: `src/autograde/reason.py` (module-level `_pellet` and `contradictions`, lines 88-99)
- Create: `tests/test_io.py`
- Modify: `tests/test_normalize.py`, `tests/test_reason.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `io.save_json(obj, path)` (same signature, now atomic); `Embedder.vector` and `Embedder.cosine` safe from several threads; `reason.contradictions(...)` (same signature) serialised by `reason._pellet_lock`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_io.py`:

```python
"""io.save_json is atomic: readers see the old file or the new one, and a failed write keeps the old one."""
import json
import os

import pytest

from autograde import io


def test_save_json_replaces_the_whole_file(tmp_path):
    p = tmp_path / "c.json"
    io.save_json({"a": 1}, p)
    io.save_json({"b": 2}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"b": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]  # no temp file left behind


def test_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    io.save_json({"a": 1}, p)

    def disk_full(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError):
        io.save_json({"b": 2}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]
```

Append to `tests/test_normalize.py`:

```python
def test_embedder_is_safe_from_several_threads(tmp_path):
    import json
    import threading

    import numpy as np

    from autograde.normalize import Embedder

    class Model:
        def encode(self, text, normalize_embeddings=True):
            return np.ones(3) / np.sqrt(3)

    e = Embedder("stub-model")
    e.path, e.cache, e._model = tmp_path / "emb.json", {}, Model()
    texts, errors = [f"kata {i}" for i in range(300)], []

    def work(chunk):
        try:
            for t in chunk:
                e.vector(t)
        except Exception as exc:  # collected: an exception in a thread does not fail the test by itself
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(texts[i::4],)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert set(json.loads(e.path.read_text(encoding="utf-8"))) == set(texts)
```

Append to `tests/test_reason.py`:

```python
@pytest.mark.pellet
def test_concurrent_answers_do_not_see_each_other(test_ontology, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(reason, "_pellet", None)  # built on the test ontology, dropped afterwards
    cases = [(i, *case_inputs(i, ref_p, students), want) for i, (_, ref_p, students, want) in enumerate(CASES)]
    with ThreadPoolExecutor(4) as pool:
        got = list(pool.map(lambda c: reason.contradictions("Q9", c[1], c[2], c[3], "pellet"), cases))
    assert got == [expected(c[0], c[4]) for c in cases]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_io.py tests/test_normalize.py tests/test_reason.py -q`
Expected: `test_failed_write_keeps_the_old_file` FAILS (the in-place write already replaced the content). `test_embedder_is_safe_from_several_threads` usually FAILS with `RuntimeError: dictionary changed size during iteration` in `errors`. It can pass by luck; the lock is what guarantees it. `test_concurrent_answers_do_not_see_each_other` FAILS or is skipped when Java is missing.

- [ ] **Step 3: Implement**

In `src/autograde/io.py`, add `import threading` to the imports (after `import shutil`) and replace `save_json`:

```python
def save_json(obj, path):
    """Atomic: another thread or the CLI reads the old file or the new one, never half of one."""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
```

In `src/autograde/normalize.py`, add `import threading` after `import re`, then change `Embedder`:

```python
    def __init__(self, model_name=None):
        self.model_name = model_name or io.load_config()["embedding_model"]
        self.path = io.ROOT / "outputs" / "cache" / "embeddings" / (self.model_name.replace("/", "__") + ".json")
        self.cache = io.load_json(self.path) if self.path.exists() else {}
        self._model = None
        self._lock = threading.Lock()  # the API shares one Embedder between request threads and the grading job

    def vector(self, text):
        with self._lock:
            if text not in self.cache:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_name)
                self.cache[text] = self._model.encode(text, normalize_embeddings=True).tolist()
                io.save_json(self.cache, self.path)
            return np.asarray(self.cache[text])
```

In `src/autograde/reason.py`, add `import threading` as the first import, then replace the module-level `_pellet = None` and the end of `contradictions`:

```python
_pellet = None
_pellet_lock = threading.Lock()  # one owlready2 World: answers reasoned at once would see each other's individuals


def contradictions(qid, refs, students, aligned, reasoner=None):
    global _pellet
    reasoner = reasoner or io.load_config()["reasoner"]
    if reasoner == "sparql":
        return contradictions_sparql(qid, refs, students, aligned)
    if reasoner != "pellet":
        raise ValueError(f"unknown reasoner {reasoner!r}")
    with _pellet_lock:
        _pellet = _pellet or PelletReasoner()
        return _pellet.contradictions(qid, refs, students, aligned)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_io.py tests/test_normalize.py tests/test_reason.py -q`
Expected: all PASS (the Pellet test is skipped without Java).

- [ ] **Step 5: Commit**

```bash
git add src/autograde/io.py src/autograde/normalize.py src/autograde/reason.py tests/test_io.py tests/test_normalize.py tests/test_reason.py
git commit -m "Make save_json atomic and lock the shared Embedder and Pellet world for multi-threaded callers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Move the view builders into the package

`app/explorer.py` and `app/rdfviz.py` have no Streamlit code. The API needs them, and part 2 deletes `app/`, so they move to `src/autograde/`.

**Files:**
- Move: `app/explorer.py` → `src/autograde/explorer.py`
- Move: `app/rdfviz.py` → `src/autograde/rdfviz.py`
- Modify: `app/streamlit_app.py` (lines 13 and 16), `app/manage.py` (lines 11-12)
- Modify: `tests/test_explorer.py` (line 4), `tests/test_rdfviz.py` (lines 5-6), `tests/test_pipeline.py` (line 68), `tests/test_no_file_reads.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `autograde.explorer` (`build(ctx, answers, params, human=None, predicates=None) -> {nodes, edges, details}`, `load_answer(run_id, answer_id)`, `NODE_TYPES`, `EDGE_TYPES`, `html(...)`) and `autograde.rdfviz` (`ontology_classes_dot`, `properties_table`, `relations_dot`, `gold_concept_dot`, `gold_reified_dot`, `alignment_dot`, `sigma_table`, `pellet_dots`, `merged_graph`, `answer_graph_names`, `run_graph_names`, `turtle_file_name`, `run_query`, `vis_graph`, `short`, `triple_text`, `PREFIXES`, `ANSWER_QUERIES`, `RUN_QUERIES`, `KG_QUERIES`, `VIS_NODE_TYPES`, `VIS_EDGE_TYPES`). Signatures are unchanged.

- [ ] **Step 1: Extend the file-read guard to subpackages (the failing test)**

In `tests/test_no_file_reads.py`, change the first line of the test body so it also covers the coming `api/` package:

```python
    files = [p for p in (io.ROOT / "src" / "autograde").rglob("*.py") if p.name != "importer.py"]
```

- [ ] **Step 2: Move the files and fix every import**

```bash
git mv app/explorer.py src/autograde/explorer.py
git mv app/rdfviz.py src/autograde/rdfviz.py
```

In `src/autograde/explorer.py`, the vendored script stays in `app/static/` until part 2 moves it to `web/`. Replace the `VIS_JS` line, drop the now-unused `from pathlib import Path`, and change the docstring's last sentence:

```python
VIS_JS = io.ROOT / "app" / "static" / "vis-network.min.js"
```

The docstring ends: `Drawn with vis-network 9.1.9, vendored in app/static/ so the demo works offline (the API serves the same graph as JSON).`

In `app/streamlit_app.py`, delete `import explorer` and `import rdfviz`, and add `explorer, rdfviz` to the existing `from autograde import baselines, db, evaluate, io, kg, pipeline` line:

```python
from autograde import baselines, db, evaluate, explorer, io, kg, pipeline, rdfviz
```

In `app/manage.py`, delete `import rdfviz` and extend the autograde import:

```python
from autograde import authoring, db, extract, gold, importer, io, rdfviz
```

In `tests/test_explorer.py`, replace `import explorer` with `from autograde import explorer`. In `tests/test_rdfviz.py`, replace `import explorer` and `import rdfviz` with `from autograde import explorer, rdfviz`. In `tests/test_pipeline.py` (inside `test_skos_preset_finds_the_broader_concept`), replace `import rdfviz` with `from autograde import rdfviz`.

- [ ] **Step 3: Check nothing else imports the old paths**

Run: `grep -rnE "^\s*(import (explorer|rdfviz)|from (explorer|rdfviz) )" app src tests`
Expected: no output.

- [ ] **Step 4: Run the whole suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all PASS (Pellet tests skipped without Java). This includes `test_app.py`, which runs the Streamlit pages with the moved modules.

- [ ] **Step 5: Commit**

```bash
git add -A app src tests
git commit -m "Move explorer and rdfviz into the autograde package so the API can use them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Schema v3, jobs, course and assessment lookups in `db`

**Files:**
- Modify: `src/autograde/schema.sql` (append)
- Modify: `src/autograde/db.py` (`SCHEMA_VERSION`, `UPGRADES`, new functions)
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (all in `autograde.db`):
  - `course(course_id) -> dict | None`, `assessment(assessment_id) -> dict | None`
  - `create_job(assessment_id, run_id, which, llm_feedback, answer_ids) -> int`
  - `job(job_id) -> dict | None`: keys `id, assessment_id, run_id, which, llm_feedback (bool), answer_ids (list), total, done, current, failures (list of {answer_id, error}), status, created, finished`
  - `running_job() -> dict | None`
  - `update_job(job_id, current, done, failures)`
  - `finish_job(job_id, status)`, where status is one of `done | cancelled | interrupted`
  - `interrupt_running_jobs() -> int`

- [ ] **Step 1: Write the failing tests**

In `tests/test_db.py`, the existing `test_version_1_database_is_upgraded_in_place` has to simulate a real version 1 file, which has no `job` table. Add one line right after its `ALTER TABLE` loop:

```python
    con.execute("DROP TABLE job")  # version 1 files predate the job table
```

Append to `tests/test_db.py`:

```python
def test_version_2_database_gets_the_job_table(demo):
    con = sqlite3.connect(db.db_path())
    con.execute("DROP TABLE job")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    assert db.questions() == ["Q9"]  # data kept
    con = db.connect()
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
    assert "answer_ids" in [r[1] for r in con.execute("PRAGMA table_info(job)")]
    con.close()


def test_course_and_assessment_lookup(fresh_db):
    db.connect(create=True).close()
    course = db.add_course("C1", "Course")
    a = db.add_assessment(course, "UTS")
    assert db.course(course) == {"id": course, "code": "C1", "name": "Course"}
    assert db.assessment(a) == {"id": a, "course_id": course, "name": "UTS"}
    assert db.course(999) is None and db.assessment(999) is None


def test_job_lifecycle(fresh_db):
    db.connect(create=True).close()
    a = db.add_assessment(db.add_course("C1", "Course"), "UTS")
    db.create_run("assessment-1", "auto", "all", "all", {}, False, "sparql", True, a)
    job_id = db.create_job(a, "assessment-1", "new", True, ["Q1_x", "Q1_y"])
    j = db.job(job_id)
    assert (j["status"], j["total"], j["done"], j["answer_ids"], j["failures"], j["llm_feedback"]) == \
        ("running", 2, 0, ["Q1_x", "Q1_y"], [], True)
    assert db.running_job()["id"] == job_id
    db.update_job(job_id, "Q1_y", 1, [{"answer_id": "Q1_x", "error": "no key"}])
    j = db.job(job_id)
    assert (j["current"], j["done"], j["failures"][0]["answer_id"]) == ("Q1_y", 1, "Q1_x")
    db.finish_job(job_id, "done")
    j = db.job(job_id)
    assert j["status"] == "done" and j["current"] is None and j["finished"] and db.running_job() is None
    other = db.create_job(a, "assessment-1", "stale", False, ["Q1_x"])
    assert db.interrupt_running_jobs() == 1 and db.job(other)["status"] == "interrupted"
    assert db.job(999) is None
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_db.py -q`
Expected: FAIL with `no such table: job` and `AttributeError: module 'autograde.db' has no attribute 'course'`.

- [ ] **Step 3: Implement**

Append to `src/autograde/schema.sql`:

```sql
-- Background grading in the API (one job at a time); answer_ids and failures are JSON lists.
CREATE TABLE job (id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessment(id),
                  run_id TEXT NOT NULL REFERENCES run(id), which TEXT NOT NULL CHECK (which IN ('new', 'stale')),
                  llm_feedback INTEGER NOT NULL, answer_ids TEXT NOT NULL, total INTEGER NOT NULL,
                  done INTEGER NOT NULL DEFAULT 0, current TEXT, failures TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'cancelled', 'interrupted')),
                  created TEXT NOT NULL, finished TEXT);
```

Edit the top of `src/autograde/schema.sql`: the first comment line says `schema version 2`. Make it `schema version 3`.

In `src/autograde/db.py`, set `SCHEMA_VERSION = 3` and add the version 2 step to `UPGRADES` (same SQL as `schema.sql`):

```python
UPGRADES = {1: ["ALTER TABLE run ADD COLUMN assessment_id INTEGER REFERENCES assessment(id)",
                "ALTER TABLE question ADD COLUMN updated TEXT",
                "ALTER TABLE result ADD COLUMN graded TEXT",
                "ALTER TABLE result ADD COLUMN reviewed TEXT",
                "ALTER TABLE result ADD COLUMN reviewed_by TEXT"],
            2: ["CREATE TABLE job (id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessment(id), "
                "run_id TEXT NOT NULL REFERENCES run(id), which TEXT NOT NULL CHECK (which IN ('new', 'stale')), "
                "llm_feedback INTEGER NOT NULL, answer_ids TEXT NOT NULL, total INTEGER NOT NULL, "
                "done INTEGER NOT NULL DEFAULT 0, current TEXT, failures TEXT NOT NULL DEFAULT '[]', "
                "status TEXT NOT NULL CHECK (status IN ('running', 'done', 'cancelled', 'interrupted')), "
                "created TEXT NOT NULL, finished TEXT)"]}
```

After `assessments(course_id)` in the courses section, add:

```python
def course(course_id):
    with tx() as c:
        row = c.execute("SELECT * FROM course WHERE id = ?", (course_id,)).fetchone()
    return None if row is None else dict(row)


def assessment(assessment_id):
    with tx() as c:
        row = c.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
    return None if row is None else dict(row)
```

Before the `# ---------- meta ----------` section, add:

```python
# ---------- grading jobs (the API's background grading) ----------

def _job(row):
    j = dict(row)
    j["answer_ids"], j["failures"] = json.loads(j["answer_ids"]), json.loads(j["failures"])
    j["llm_feedback"] = bool(j["llm_feedback"])
    return j


def create_job(assessment_id, run_id, which, llm_feedback, answer_ids):
    answer_ids = list(answer_ids)
    with tx() as c:
        return c.execute("INSERT INTO job (assessment_id, run_id, which, llm_feedback, answer_ids, total, status, "
                         "created) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                         (assessment_id, run_id, which, int(llm_feedback), _dumps(answer_ids), len(answer_ids),
                          _now())).lastrowid


def job(job_id):
    with tx() as c:
        row = c.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return None if row is None else _job(row)


def running_job():
    with tx() as c:
        row = c.execute("SELECT * FROM job WHERE status = 'running' ORDER BY id LIMIT 1").fetchone()
    return None if row is None else _job(row)


def update_job(job_id, current, done, failures):
    with tx() as c:
        c.execute("UPDATE job SET current = ?, done = ?, failures = ? WHERE id = ?",
                  (current, done, _dumps(failures), job_id))


def finish_job(job_id, status):
    with tx() as c:
        c.execute("UPDATE job SET status = ?, current = NULL, finished = ? WHERE id = ?", (status, _now(), job_id))


def interrupt_running_jobs():
    """At server start: a job still marked running lost its thread when the previous server stopped."""
    with tx() as c:
        return c.execute("UPDATE job SET status = 'interrupted', current = NULL, finished = ? "
                         "WHERE status = 'running'", (_now(),)).rowcount
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_db.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autograde/schema.sql src/autograde/db.py tests/test_db.py
git commit -m "Add schema v3 with the job table, job functions and course and assessment lookups" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: OWL export for Protégé

**Files:**
- Create: `src/autograde/owl_export.py`
- Create: `tests/test_owl_export.py`
- Modify: `README.md` (new section "Open in Protégé")

**Interfaces:**
- Consumes: `kg.get_graph`, `kg.gold_graph_name`, `kg.answer_graph_name`, `io.ontology_graph`, `gold.load`, `gold.ref_iri`, `rdfviz.triple_text` (Task 2), `feedback.triple_label`, `db.run`, `db.results`.
- Produces: `owl_export.export_iri(run_id, answer_id=None) -> URIRef`, `owl_export.build(run_id, answer_id=None) -> rdflib.Graph`, `owl_export.rdfxml(run_id, answer_id=None) -> bytes`. Unknown run, an answer not graded in the run, or a run with no results all raise `LookupError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_owl_export.py`:

```python
"""OWL export for Protégé: self-contained and declared, without the app's inferences, so the reasoner re-derives them."""
import pytest
from rdflib import OWL, RDF, RDFS, Graph, Namespace

from autograde import db, gold, importer, io, owl_export, pipeline
from autograde.io import AG, ANS
from test_pipeline import STUB

SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
DECLARED = (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
RUN = "owl-export-test"


@pytest.fixture
def run(fresh_db):
    importer.import_files()
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    db.create_run(RUN, "gold", "all", "Q1", ctx.params, False, "sparql", True)
    texts = db.answers(include_synthetic=True).set_index("answer_id").text
    for aid in ("Q1_A07", "Q1_A08"):
        pipeline.run_answer(ctx, aid, texts[aid], "gold", RUN, use_llm_feedback=False)
    return RUN


def test_self_contained_without_the_apps_inferences(run):
    g = Graph().parse(data=owl_export.rdfxml(run), format="xml")
    assert set(g.subjects(RDF.type, OWL.Ontology)) == {owl_export.export_iri(run)}
    rules = len(set(io.ontology_graph().subjects(RDF.type, SWRL.Imp)))
    assert rules > 0 and len(set(g.subjects(RDF.type, SWRL.Imp))) == rules
    assert db.result(run, "Q1_A08")["trace"]["contradictions"]  # the app found one, so leaving it out matters
    assert list(g.triples((None, AG.contradicts, None))) == []
    assert (ANS["Q1_A07"], RDF.type, OWL.NamedIndividual) in g


def test_every_term_an_individual_uses_is_declared(run):
    g = owl_export.build(run)
    individuals = set(g.subjects(RDF.type, OWL.NamedIndividual))
    used = {p for s in individuals for p in g.predicates(s)} - {RDF.type, RDFS.label, RDFS.comment}
    assert {p for p in used if not any((p, RDF.type, k) in g for k in DECLARED)} == set()
    classes = {o for s in individuals for o in g.objects(s, RDF.type)} - {OWL.NamedIndividual}
    assert {c for c in classes if (c, RDF.type, OWL.Class) not in g} == set()


def test_labels_one_answer_and_the_corrected_ledger(run):
    db.add_overrides([{"answer_id": "Q1_A07", "reference_id": "R3", "status": "MATCHED", "by": "DS",
                       "date": "2026-10-27", "reason": "air disebut"}])
    pipeline.apply_corrections(run, "Q1_A07")
    g = owl_export.build(run, "Q1_A07")
    entry = ANS["L_Q1_A07_R3"]
    assert list(g.objects(entry, AG.status)) == [AG.Cocok]  # the corrected status, and only that one
    assert str(g.value(entry, RDFS.label)).startswith("R3 · MATCHED")
    assert g.value(gold.ref_iri("Q1", "R1"), RDFS.label) is not None
    assert g.value(ANS["Q1_A07_t1"], RDFS.label) is not None
    assert list(g.triples((ANS["Q1_A08"], None, None))) == []  # one-answer scope


def test_unknown_run_or_answer(run):
    with pytest.raises(LookupError):
        owl_export.build("no-such-run")
    with pytest.raises(LookupError):
        owl_export.build(run, "Q1_A01")


@pytest.mark.pellet
@pytest.mark.parametrize("reasoner", ["pellet", "hermit"])
def test_the_reasoner_rederives_the_apps_contradictions(run, tmp_path, reasoner):
    import owlready2
    owlready2.JAVA_EXE = io.java_exe()
    path = tmp_path / "export.owl"
    path.write_bytes(owl_export.rdfxml(run))
    world = owlready2.World()
    world.get_ontology(path.as_uri()).load()
    if reasoner == "pellet":
        owlready2.sync_reasoner_pellet(world, infer_property_values=True, infer_data_property_values=True, debug=0)
    else:
        owlready2.sync_reasoner_hermit(world, infer_property_values=True, debug=0)
    got = {(s.name, o.name) for s, o in world.search_one(iri=str(AG.contradicts)).get_relations()}
    want = {(t, io.local_name(gold.ref_iri("Q1", r)))
            for aid in ("Q1_A07", "Q1_A08") for t, r in db.result(run, aid)["trace"]["contradictions"]}
    assert want and got == want
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_owl_export.py -q`
Expected: FAIL with `ImportError: cannot import name 'owl_export'`.

- [ ] **Step 3: Implement `src/autograde/owl_export.py`**

```python
"""One run (or one answer) as a self-contained OWL file for Protégé: browse it, run the reasoner, query it.

The file holds the ontology with its SWRL rules, the gold graph of every question involved, each answer's graph and
its effective ledger. The app's own ag:contradicts inferences are left out so the reasoner in Protégé derives them
again. Labels and declarations are added here only; the knowledge graph itself is unchanged.
"""
from urllib.parse import quote

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SKOS

from autograde import db, gold, io, kg, rdfviz
from autograde.feedback import triple_label
from autograde.io import AG, ANS
from autograde.models import LedgerEntry, StudentTriple

ONTOLOGY_IRI = URIRef("http://example.org/autograde/ontology")
EXPORT_BASE = "http://example.org/autograde/export/"
# Used by the gold graphs but not declared in autograde.owl; undeclared, Protégé guesses their type or refuses OWL DL.
DECLARATIONS = [(SKOS.Concept, RDF.type, OWL.Class), (SKOS.broader, RDF.type, OWL.ObjectProperty)]


def export_iri(run_id, answer_id=None):
    return URIRef(EXPORT_BASE + quote(run_id) + (f"/{quote(answer_id)}" if answer_id else ""))


def _results(run_id, answer_id):
    if db.run(run_id) is None:
        raise LookupError(f"unknown run {run_id}")
    results = db.results(run_id)
    if answer_id is not None:
        if answer_id not in results:
            raise LookupError(f"{answer_id} is not graded in run {run_id}")
        results = {answer_id: results[answer_id]}
    if not results:
        raise LookupError(f"run {run_id} has no graded answers")
    return results


def build(run_id, answer_id=None):
    results = _results(run_id, answer_id)
    g = io.bind_namespaces(Graph())
    for t in io.ontology_graph():  # embedded, not owl:imports: Protégé would try to fetch the ontology IRI
        if t[0] != ONTOLOGY_IRI:
            g.add(t)
    iri = export_iri(run_id, answer_id)
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, RDFS.comment, Literal(f"AutoGrade-RDF run {run_id}: {', '.join(sorted(results))}. ag:contradicts is "
                                      "left out; start the reasoner to infer it.")))
    for t in DECLARATIONS:
        g.add(t)
    abox = Graph()
    for qid in sorted({r["question_id"] for r in results.values()}):
        abox += kg.get_graph(kg.gold_graph_name(qid))
        for ref in gold.load(qid)[2]:
            g.add((gold.ref_iri(qid, ref.id), RDFS.label, Literal(triple_label(ref))))
    for aid, r in sorted(results.items()):
        # the corrected ledger when there is one: both share entry IRIs and ag:status is functional
        kind = "ledger_corrected" if r["ledger_corrected"] else "ledger"
        abox += kg.get_graph(kg.answer_graph_name(run_id, aid, "answer"), kg.answer_graph_name(run_id, aid, kind))
        for t in map(StudentTriple.model_validate, r["students"]):
            g.add((ANS[t.id], RDFS.label, Literal(rdfviz.triple_text(t))))
        for e in map(LedgerEntry.model_validate, r["ledger_corrected"] or r["ledger"]):
            g.add((ANS[e.entry_id], RDFS.label, Literal(f"{e.reference_id} · {e.status} · {e.credit:g}")))
    abox.remove((None, AG.contradicts, None))
    for s in set(abox.subjects(RDF.type, None)):
        g.add((s, RDF.type, OWL.NamedIndividual))
    g += abox
    return g


def rdfxml(run_id, answer_id=None):
    return build(run_id, answer_id).serialize(format="xml", encoding="utf-8")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_owl_export.py -q`
Expected: all PASS. The two reasoner tests are skipped without Java.

If `test_the_reasoner_rederives_the_apps_contradictions[hermit]` fails while `[pellet]` passes, HermiT doesn't accept one of the SWRL rules (the spec lists this as unverified). Stop and report it with the error, and don't change the rules. The fallback is to tell Protégé users to install the Pellet plugin, and that is the user's call.

- [ ] **Step 5: Add the Protégé section to `README.md`**

Insert before the line that starts with `Full command list:`:

```markdown
## Open in Protégé

The API exports one graded answer or a whole run as an OWL file: `GET /api/export/owl?run=<run>[&answer=<answer>]`. An assessment's run is `assessment-<id>`. The file holds the ontology and its SWRL rules, each question's key, every answer's student triples with their sentences (`prov:wasDerivedFrom`) and the reasoner's input (`alignedSubject`/`alignedObject`), and the ledger (the corrected one when you made corrections). The app's own `ag:contradicts` inferences are left out, so the reasoner derives them again.

1. *File → Open* the `.owl` file.
2. *Reasoner → HermiT*, then *Reasoner → Start reasoner*.
3. Under *Individuals*, pick a student triple of an answer with a contradiction: the inferred `contradicts` link shows in yellow.
4. *DL Query* tab: `LedgerEntry and status value Hilang` lists every missing reference triple; `ReferenceTriple and criterion value Q1_K1_Bahan` lists the triples of one criterion.
```

- [ ] **Step 6: Commit**

```bash
git add src/autograde/owl_export.py tests/test_owl_export.py README.md
git commit -m "Add the OWL export for Protégé: embedded ontology, declarations, labels, no app inferences" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: API shell, courses, security and `serve`

**Files:**
- Modify: `requirements.txt`
- Create: `src/autograde/api/__init__.py`, `src/autograde/api/app.py`, `src/autograde/api/deps.py`, `src/autograde/api/schemas.py`, `src/autograde/api/routes/__init__.py`, `src/autograde/api/routes/courses.py`
- Create: `web/index.html`
- Modify: `src/autograde/cli.py` (new `cmd_serve`, parser entry, the empty-database check in `main`)
- Modify: `tests/conftest.py` (append the `client` fixture)
- Create: `tests/test_api_app.py`
- Modify: `README.md` (Run section)

**Interfaces:**
- Consumes: `db.course`, `db.assessment`, `db.interrupt_running_jobs` (Task 3).
- Produces:
  - `autograde.api.app.create_app() -> FastAPI` and `ROUTERS` (a list later tasks extend)
  - `autograde.api.deps`: `MAX_UPLOAD`, `course_or_404(course_id)`, `assessment_or_404(assessment_id)`, `question_or_404(qid)`, `run_or_404(run_id)`, `result_or_404(run_id, answer_id)`, `read_upload(file) -> bytes`
  - `autograde.api.schemas`: `Name` (stripped, non-empty `str`), `table(df) -> {"columns", "rows"}`, `CourseIn`, `AssessmentIn`
  - Pytest fixture `client`: a `TestClient` on a fresh import of the demo data (course `DEMO`, one assessment with question `Q1` and 7 annotated synthetic answers), offline grading.

- [ ] **Step 1: Install and pin FastAPI**

Run: `conda run -n semantic_web pip install fastapi`, then `conda run -n semantic_web pip show fastapi` and `conda run -n semantic_web pip check`.
Expected: installed, and `pip check` reports no broken requirements. If it lists one (for example a starlette that streamlit can't use), stop and report it.

Add `fastapi==<the version pip show printed>` to `requirements.txt` in its alphabetical place (after `docstring-parser`). If pip changed the version of an already pinned package (e.g. `starlette`), update that pin to what `pip show` reports.

- [ ] **Step 2: Write the failing tests**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def client(fresh_db, monkeypatch):
    """The API on a fresh import of the demo data, grading offline: stub embeddings, SPARQL reasoner, no API key."""
    from fastapi.testclient import TestClient

    from autograde import importer, llm, pipeline
    from autograde.api.app import create_app
    from test_pipeline import STUB
    importer.import_files()
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)  # a real key in .env must never reach a test
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        yield c
```

Create `tests/test_api_app.py`:

```python
"""The API shell: courses, error mapping, the security checks, the web mount and the serve command."""
from fastapi.testclient import TestClient

from autograde import cli, db, kg
from autograde.api.app import create_app


def test_courses_and_assessments(client):
    r = client.post("/api/courses", json={"code": " SW1 ", "name": "Semantic Web"})
    assert r.status_code == 201 and r.json()["code"] == "SW1"
    course = r.json()["id"]
    assert client.post("/api/courses", json={"code": "SW1", "name": "Again"}).status_code == 409
    assert client.post(f"/api/courses/{course}/assessments", json={"name": "UTS"}).status_code == 201
    assert client.post(f"/api/courses/{course}/assessments", json={"name": "UTS"}).status_code == 409
    assert [(a["name"], a["questions"]) for a in client.get(f"/api/courses/{course}/assessments").json()] == \
        [("UTS", [])]
    assert client.get(f"/api/courses/{course}/students").json() == \
        {"columns": ["external_id", "name", "answers"], "rows": []}
    assert {"DEMO", "SW1"} <= {c["code"] for c in client.get("/api/courses").json()}


def test_unknown_ids_and_invalid_bodies(client):
    r = client.get("/api/courses/999/assessments")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "message": "unknown course 999", "details": []}
    r = client.post("/api/courses", json={"code": "  ", "name": "x"})
    assert r.status_code == 422 and r.json()["error"] == "invalid" and r.json()["details"][0].startswith("body.code")


def test_store_busy_and_unexpected_errors(client, monkeypatch):
    def busy():
        raise kg.KGBusyError("the knowledge graph store is in use by another process")

    monkeypatch.setattr(db, "courses", busy)
    r = client.get("/api/courses")
    assert r.status_code == 503 and r.headers["retry-after"] == "2" and r.json()["error"] == "busy"

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "courses", boom)
    with TestClient(create_app(), base_url="http://127.0.0.1", raise_server_exceptions=False) as c:
        r = c.get("/api/courses")
    assert r.status_code == 500 and r.json() == {"error": "internal", "message": "boom", "details": []}


def test_cross_origin_writes_and_foreign_hosts_are_refused(client):
    body = {"code": "X1", "name": "x"}
    r = client.post("/api/courses", json=body, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert client.post("/api/courses", json=body, headers={"Origin": "http://127.0.0.1"}).status_code == 201
    assert client.get("/api/courses", headers={"Origin": "http://evil.example"}).status_code == 200  # reads are safe
    assert client.get("/api/courses", headers={"Host": "evil.example"}).status_code == 400


def test_web_folder_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200 and "AutoGrade-RDF" in r.text
    assert client.get("/api/nope").status_code == 404


def test_startup_creates_an_empty_database(fresh_db):
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        assert c.get("/api/courses").json() == []


def test_serve_binds_localhost_on_an_empty_database(fresh_db, monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    cli.main(["serve", "--port", "8123"])
    assert calls == [{"host": "127.0.0.1", "port": 8123}]
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_app.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'autograde.api'`.

- [ ] **Step 4: Implement**

`src/autograde/api/__init__.py`:

```python
"""Local JSON API over the grading core (spec: docs/superpowers/specs/2026-10-27-api-backend-design.md)."""
```

`src/autograde/api/routes/__init__.py`: an empty file.

`src/autograde/api/schemas.py`:

```python
"""Request models (validation and the /docs page) and the one response helper for tables."""
import json
from typing import Annotated

from pydantic import BaseModel, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def table(df):
    """A DataFrame as {columns, rows}: NaN and None become null, numpy numbers plain JSON numbers."""
    data = json.loads(df.to_json(orient="split", index=False, date_format="iso"))
    return {"columns": data["columns"], "rows": data["data"]}


class CourseIn(BaseModel):
    code: Name
    name: Name


class AssessmentIn(BaseModel):
    name: Name
```

`src/autograde/api/deps.py`:

```python
"""Lookups that turn an unknown id into a 404, and the upload size limit."""
from fastapi import HTTPException

from autograde import db

MAX_UPLOAD = 10 * 1024 * 1024


def course_or_404(course_id):
    c = db.course(course_id)
    if c is None:
        raise HTTPException(404, f"unknown course {course_id}")
    return c


def assessment_or_404(assessment_id):
    a = db.assessment(assessment_id)
    if a is None:
        raise HTTPException(404, f"unknown assessment {assessment_id}")
    return a


def question_or_404(qid):
    try:
        return db.question(qid)
    except KeyError:
        raise HTTPException(404, f"unknown question {qid}") from None


def run_or_404(run_id):
    r = db.run(run_id)
    if r is None:
        raise HTTPException(404, f"unknown run {run_id}")
    return r


def result_or_404(run_id, answer_id):
    r = db.result(run_id, answer_id)
    if r is None:
        raise HTTPException(404, f"{answer_id} is not graded in run {run_id}")
    return r


def read_upload(file):
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{file.filename} is larger than 10 MB")
    return data
```

`src/autograde/api/routes/courses.py`:

```python
"""Courses, assessments and students (Streamlit: Mata Kuliah)."""
from fastapi import APIRouter

from autograde import db
from autograde.api import deps
from autograde.api.schemas import AssessmentIn, CourseIn, table

router = APIRouter(tags=["courses"])


@router.get("/courses")
def list_courses():
    return db.courses()


@router.post("/courses", status_code=201)
def add_course(body: CourseIn):
    return db.course(db.add_course(body.code, body.name))


@router.get("/courses/{course_id}/assessments")
def list_assessments(course_id: int):
    deps.course_or_404(course_id)
    return [{**a, "questions": db.questions(a["id"])} for a in db.assessments(course_id)]


@router.post("/courses/{course_id}/assessments", status_code=201)
def add_assessment(course_id: int, body: AssessmentIn):
    deps.course_or_404(course_id)
    return db.assessment(db.add_assessment(course_id, body.name))


@router.get("/courses/{course_id}/students")
def list_students(course_id: int):
    deps.course_or_404(course_id)
    return table(db.students(course_id))
```

`src/autograde/api/app.py`:

```python
"""The local JSON API (/api) and the frontend's files (/) in one process.

Local only: no login, so the server binds 127.0.0.1, refuses foreign Host headers (DNS rebinding) and refuses writes
from other origins (any web page could otherwise POST a form here, e.g. to start a paid LLM grading job).
"""
import logging
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from autograde import db, gold, importer, io, kg, llm
from autograde.api.routes import courses

WEB = io.ROOT / "web"
HOSTS = ["localhost", "127.0.0.1"]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CODES = {400: "bad_request", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict",
         413: "too_large", 422: "invalid", 503: "busy"}
ROUTERS = [courses.router]
log = logging.getLogger("uvicorn.error")


def error(status, message, details=None, headers=None):
    return JSONResponse({"error": CODES.get(status, "internal" if status >= 500 else "error"), "message": message,
                         "details": details or []}, status_code=status, headers=headers)


def startup():
    db.connect(create=True).close()  # a new install starts in the app; SchemaVersionError stops the server
    kg.sync_ontology()
    db.interrupt_running_jobs()


@asynccontextmanager
async def lifespan(app):
    startup()
    yield


def create_app():
    app = FastAPI(title="AutoGrade-RDF", lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if isinstance(exc.detail, list):
            return error(exc.status_code, "invalid input", exc.detail, exc.headers)
        return error(exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error(422, "invalid request", [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()])

    @app.exception_handler(importer.ImportDataError)
    @app.exception_handler(gold.GoldError)
    async def invalid_data(request, exc):
        return error(422, "invalid input", str(exc).split("; "))

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request, exc):
        return error(409, f"already exists ({exc})")

    @app.exception_handler(kg.KGBusyError)
    async def busy(request, exc):
        return error(503, str(exc), headers={"Retry-After": "2"})

    @app.exception_handler(llm.LLMUnavailable)
    async def no_llm(request, exc):
        return error(400, str(exc))

    @app.exception_handler(Exception)
    async def internal(request, exc):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error(500, str(exc))

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in SAFE_METHODS and origin is not None \
                and urlsplit(origin).netloc != request.headers.get("host"):
            return error(403, "cross-origin request refused")
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")  # last: /api and /docs match first
    return app
```

`web/index.html`:

```html
<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoGrade-RDF</title>
</head>
<body>
  <main>
    <h1>AutoGrade-RDF</h1>
    <p>API berjalan. Halaman antarmuka dibuat pada bagian 2 (frontend).</p>
    <p><a href="/docs">Dokumentasi API</a></p>
  </main>
</body>
</html>
```

In `src/autograde/cli.py`, add after `cmd_db`:

```python
def cmd_serve(args):
    import uvicorn

    from autograde.api.app import create_app
    print(f"AutoGrade-RDF on http://127.0.0.1:{args.port} (API docs: /docs)")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)  # local only: there is no login
```

In `main`, add the parser entry after the `db` sub-parser:

```python
    s = sub.add_parser("serve", help="run the local API and web app on http://127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)
```

and let `serve` start on an empty database like `db` does:

```python
    if args.command not in ("db", "serve"):
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_app.py tests/test_cli.py tests/test_no_file_reads.py -q`
Expected: all PASS.

- [ ] **Step 6: Document `serve`**

In `README.md`, inside the `## Run` code block, add as the last line (after `streamlit run app/streamlit_app.py`):

```bash
python -m autograde serve                          # local API + web app on http://127.0.0.1:8000 (API docs at /docs)
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/autograde/api src/autograde/cli.py web tests/conftest.py tests/test_api_app.py README.md
git commit -m "Add the local API shell: error mapping, host and origin checks, courses, web mount and the serve command" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Question routes

**Files:**
- Modify: `src/autograde/importer.py` (`QuestionExistsError`, used in `save_question`)
- Modify: `src/autograde/api/schemas.py` (append the draft models)
- Modify: `src/autograde/api/app.py` (409 for `QuestionExistsError`, register the router)
- Create: `src/autograde/api/routes/questions.py`
- Create: `tests/test_api_questions.py`

**Interfaces:**
- Consumes: `deps.question_or_404`, `deps.assessment_or_404`, `deps.read_upload`, `authoring.to_tables / from_tables / question_files / question_zip`, `importer.save_question / add_question / validate_question / checked_relations`, `rdfviz.gold_concept_dot / gold_reified_dot`, `gold.to_graph`.
- Produces:
  - `importer.QuestionExistsError(ImportDataError)`
  - `schemas.QuestionDraft` with `.tables() -> dict` (the `authoring` draft with DataFrames) and `QuestionDraft.from_tables(draft) -> QuestionDraft`; `CriterionRow`, `ConceptRow`, `TripleRow`, `QuestionId`, `NewQuestion`, `PreviewRequest`
  - Endpoints: `GET /questions`, `GET /assessments/{id}/questions`, `GET /questions/{qid}`, `POST /questions`, `PUT /questions/{qid}`, `POST /questions/preview`, `POST /assessments/{id}/questions/upload`, `GET /questions/{qid}/files.zip`, `GET /predicates?lang=`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_questions.py`:

```python
"""Questions: list, read, editor save and live preview, file upload and download."""
import io as _io
import zipfile

from autograde import authoring, db


def demo_assessment(client):
    course = next(c for c in client.get("/api/courses").json() if c["code"] == "DEMO")["id"]
    return client.get(f"/api/courses/{course}/assessments").json()[0]["id"]


def test_lists_and_reads(client):
    aid = demo_assessment(client)
    q1 = next(q for q in client.get("/api/questions").json() if q["id"] == "Q1")
    assert q1["assessment_id"] == aid and q1["answers"] >= 7 and q1["language"] == "id"
    assert [q["id"] for q in client.get(f"/api/assessments/{aid}/questions").json()] == db.questions(aid)
    q = client.get("/api/questions/Q1").json()
    assert [t["id"] for t in q["draft"]["triples"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert q["draft"]["criteria"][0]["id"] == "K1_Bahan" and q["rubric"]["question_id"] == "Q1"
    assert client.get("/api/questions/Q404").status_code == 404


def test_preview_valid_and_invalid(client):
    draft = client.get("/api/questions/Q1").json()["draft"]
    r = client.post("/api/questions/preview", json={"id": "Q7", "draft": draft}).json()
    assert r["valid"] and r["graph"] == "urn:ag:gold:Q7" and "digraph" in r["concept_dot"]
    assert "ReferenceTriple" in r["turtle"] and "question_id: Q7" in r["yaml"]
    draft["triples"][0]["criterion"] = "K9_Tidak_Ada"
    r = client.post("/api/questions/preview", json={"id": "Q7", "draft": draft}).json()
    assert not r["valid"] and r["errors"]
    assert client.post("/api/questions/preview", json={"id": "Q 7", "draft": draft}).status_code == 422


def test_create_edit_and_duplicates(client):
    aid = demo_assessment(client)
    draft = client.get("/api/questions/Q1").json()["draft"]
    r = client.post("/api/questions", json={"id": "Q1B", "assessment_id": aid, "draft": draft})
    assert r.status_code == 201 and r.json() == {"id": "Q1B"}
    assert client.get("/api/questions/Q1B").json()["draft"]["triples"] == draft["triples"]
    r = client.post("/api/questions", json={"id": "Q1B", "assessment_id": aid, "draft": draft})
    assert r.status_code == 409
    draft["prompt"] = "Jelaskan fotosintesis dengan singkat."
    r = client.put("/api/questions/Q1B", json=draft)
    assert r.status_code == 200 and db.question("Q1B")["prompt"] == draft["prompt"]
    draft["triples"][0]["p"] = "terbang"
    r = client.put("/api/questions/Q1B", json=draft)
    assert r.status_code == 422 and r.json()["details"]
    assert client.put("/api/questions/Q404", json=draft).status_code == 404


def test_upload_and_zip(client):
    aid = demo_assessment(client)
    q = db.question("Q1")
    files = authoring.question_files(q["prompt"], q["reference_answer"], {**q["rubric"], "question_id": "Q1U"},
                                     {**q["gold"], "question_id": "Q1U"})
    upload = [("files", (name, text.encode("utf-8"))) for name, text in files.items()]
    r = client.post(f"/api/assessments/{aid}/questions/upload", files=upload)
    assert r.status_code == 201 and r.json() == {"id": "Q1U"}
    assert client.post(f"/api/assessments/{aid}/questions/upload", files=upload).status_code == 409
    bad = [("files", ("question.md", b"\xff\xfe\x00"))]
    assert client.post(f"/api/assessments/{aid}/questions/upload", files=bad).status_code == 422
    r = client.get("/api/questions/Q1/files.zip")
    assert r.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(_io.BytesIO(r.content)).namelist()) == \
        ["Q1/gold.yaml", "Q1/question.md", "Q1/reference_answer.md", "Q1/rubric.yaml"]


def test_predicates_for_the_editor(client):
    ids = [p["id"] for p in client.get("/api/predicates?lang=id").json()]
    assert "menggunakan" in ids and "other" not in ids and "is_a" not in ids
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_questions.py -q`
Expected: FAIL with 404s (no question routes yet).

- [ ] **Step 3: Implement**

In `src/autograde/importer.py`, after `class ImportDataError`:

```python
class QuestionExistsError(ImportDataError):
    pass
```

and in `save_question`, raise it for the existing id:

```python
    if assessment_id is not None and exists:
        raise QuestionExistsError(f"question {qid} already exists; change question_id in rubric.yaml and gold.yaml")
```

Append to `src/autograde/api/schemas.py` (and add the imports `from typing import Annotated, Literal`, `import pandas as pd`, `from autograde import authoring`):

```python
QuestionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]


class CriterionRow(BaseModel):
    id: str = ""
    description: str = ""


class ConceptRow(BaseModel):
    concept: str = ""
    aliases: list[str] = []
    broader: list[str] = []


class TripleRow(BaseModel):
    id: str = ""
    s: list[str] = []
    p: str = ""
    o: str = ""
    criterion: str = ""
    weight: float | None = None


class QuestionDraft(BaseModel):
    """The editor's tables (authoring.to_tables) as JSON."""
    prompt: str = ""
    reference_answer: str = ""
    language: Literal["id", "en"] = "id"
    validated_by: str = ""
    criteria: list[CriterionRow] = []
    concepts: list[ConceptRow] = []
    triples: list[TripleRow] = []

    def tables(self):
        def frame(rows, columns):
            return pd.DataFrame([r.model_dump() for r in rows], columns=columns)
        return {"prompt": self.prompt, "reference_answer": self.reference_answer, "language": self.language,
                "validated_by": self.validated_by, "criteria": frame(self.criteria, authoring.CRITERIA),
                "concepts": frame(self.concepts, authoring.CONCEPTS), "triples": frame(self.triples, authoring.TRIPLES)}

    @classmethod
    def from_tables(cls, draft):
        return cls(**{k: json.loads(v.to_json(orient="records")) if isinstance(v, pd.DataFrame) else v
                      for k, v in draft.items()})


class NewQuestion(BaseModel):
    id: QuestionId
    assessment_id: int
    draft: QuestionDraft


class PreviewRequest(BaseModel):
    id: QuestionId
    draft: QuestionDraft
    base_id: str | None = None  # the question edited or copied: its keys the editor doesn't manage are kept
```

`src/autograde/api/routes/questions.py`:

```python
"""Questions: list, read, save from the editor's tables, live preview, file upload and download (Editor Soal)."""
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from autograde import authoring, db, extract, gold, importer, io, kg, rdfviz
from autograde.api import deps
from autograde.api.schemas import NewQuestion, PreviewRequest, QuestionDraft

router = APIRouter(tags=["questions"])


def _summary(qid, counts):
    q = db.question(qid)
    return {"id": qid, "assessment_id": q["assessment_id"], "prompt": q["prompt"],
            "language": q["rubric"].get("language", "id"), "answers": int(counts.get(qid, 0)),
            "results": db.result_count(qid)}


def _answer_counts():
    return db.answers(include_synthetic=True).question_id.value_counts()


def _checked(qid, draft, base):
    try:
        return authoring.from_tables(qid, draft.tables(), base)
    except ValueError as e:  # e.g. a concept listed twice; save_question validates the rest
        raise HTTPException(422, [str(e)]) from None


@router.get("/questions")
def list_questions():
    counts = _answer_counts()
    return [_summary(q, counts) for q in db.questions()]


@router.get("/assessments/{assessment_id}/questions")
def assessment_questions(assessment_id: int):
    deps.assessment_or_404(assessment_id)
    counts = _answer_counts()
    return [_summary(q, counts) for q in db.questions(assessment_id)]


@router.get("/questions/{qid}")
def get_question(qid: str):
    q = deps.question_or_404(qid)
    return {**q, "draft": QuestionDraft.from_tables(authoring.to_tables(q)), "results": db.result_count(qid)}


@router.post("/questions", status_code=201)
def create_question(body: NewQuestion):
    deps.assessment_or_404(body.assessment_id)
    rubric, gold_raw = _checked(body.id, body.draft, None)
    importer.save_question(body.id, body.draft.prompt.strip(), body.draft.reference_answer.strip(), rubric, gold_raw,
                           body.assessment_id)
    return {"id": body.id}


@router.put("/questions/{qid}")
def update_question(qid: str, draft: QuestionDraft):
    base = deps.question_or_404(qid)
    rubric, gold_raw = _checked(qid, draft, base)
    importer.save_question(qid, draft.prompt.strip(), draft.reference_answer.strip(), rubric, gold_raw)
    return {"id": qid, "stale_results": db.result_count(qid)}


@router.post("/questions/preview")
def preview(body: PreviewRequest):
    """The live preview: the validation errors, or the gold graph this draft would store. Nothing is saved."""
    base = deps.question_or_404(body.base_id) if body.base_id else None
    d = body.draft
    try:
        rubric, gold_raw = authoring.from_tables(body.id, d.tables(), base)
        refs = importer.validate_question(d.prompt.strip(), d.reference_answer.strip(), rubric, gold_raw,
                                          importer.checked_relations())
    except ValueError as e:
        return {"valid": False, "errors": str(e).split("; ")}
    files = authoring.question_files(d.prompt, d.reference_answer, rubric, gold_raw)
    return {"valid": True, "errors": [], "graph": kg.gold_graph_name(body.id),
            "concept_dot": rdfviz.gold_concept_dot(refs, gold_raw["concepts"]),
            "reified_dot": rdfviz.gold_reified_dot(body.id, refs),
            "turtle": gold.to_graph(body.id, refs, rubric, gold_raw["concepts"]).serialize(format="turtle"),
            "yaml": files["rubric.yaml"] + "\n---\n" + files["gold.yaml"]}


@router.post("/assessments/{assessment_id}/questions/upload", status_code=201)
def upload_question(assessment_id: int, files: list[UploadFile] = File(...)):
    """The four files of data/questions/<qid>/ (question.md, reference_answer.md, rubric.yaml, gold.yaml)."""
    deps.assessment_or_404(assessment_id)
    try:
        texts = {f.filename: deps.read_upload(f).decode("utf-8") for f in files}
    except UnicodeDecodeError as e:
        raise HTTPException(422, f"question files must be UTF-8 text ({e})") from None
    return {"id": importer.add_question(assessment_id, texts)}


@router.get("/questions/{qid}/files.zip")
def question_zip(qid: str):
    q = deps.question_or_404(qid)
    files = authoring.question_files(q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    return Response(authoring.question_zip(qid, files), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{qid}.zip"'})


@router.get("/predicates")
def predicates(lang: Literal["id", "en"] = "id"):
    """The predicates a key in this language may use (the editor's dropdown); `other` is only for extraction."""
    return [p for p in extract.for_language(io.load_predicates(), lang)["predicates"] if p["id"] != "other"]
```

In `src/autograde/api/app.py`, change the routes import and `ROUTERS`:

```python
from autograde.api.routes import courses, questions
```

```python
ROUTERS = [courses.router, questions.router]
```

and add this handler next to the other data handlers (Starlette picks the most specific class, so it wins over `ImportDataError`):

```python
    @app.exception_handler(importer.QuestionExistsError)
    async def question_exists(request, exc):
        return error(409, str(exc))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_questions.py tests/test_importer.py tests/test_app.py -q`
Expected: all PASS (`test_importer.py` and `test_app.py` still accept the subclassed error).

- [ ] **Step 5: Commit**

```bash
git add src/autograde/importer.py src/autograde/api tests/test_api_questions.py
git commit -m "Add the question routes: list, read, editor save, live preview, upload, zip and predicates" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: CSV import routes

**Files:**
- Modify: `src/autograde/api/schemas.py` (append the mapping models)
- Modify: `src/autograde/api/app.py` (register the router)
- Create: `src/autograde/api/routes/imports.py`
- Create: `tests/test_api_imports.py`

**Interfaces:**
- Consumes: `deps.read_upload`, `deps.course_or_404`, `importer.answers_from_table(df, id_col, name_cols, columns, split)`, `importer.scores_from_table(df, id_col, qid, columns, rater_id)`, `db.import_course_answers`, `db.add_human_scores`.
- Produces:
  - `schemas.AnswerSource`, `schemas.AnswerMapping` (with `.source_map()` in the importer's `qid -> (column, None | (filter column, value))` form), `schemas.ScoreMapping`
  - Endpoints: `POST /imports/preview` (multipart `file`) → `{"count", "columns", "rows"}`. `POST /courses/{id}/answers?dry_run=` and `POST /courses/{id}/scores?dry_run=` (multipart `file` plus a form field `mapping` holding JSON).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_imports.py`:

```python
"""LMS CSV imports: preview, answers (wide and long), lecturer scores, and the mistakes people make."""
import json

from autograde import db
from autograde.api import deps


def demo_course(client):
    return next(c for c in client.get("/api/courses").json() if c["code"] == "DEMO")["id"]


def post(client, path, text, mapping, **params):
    return client.post(path, params=params, files={"file": ("lms.csv", text.encode("utf-8"))},
                       data={"mapping": json.dumps(mapping)})


WIDE = "nim,nama,jwb\n2201,Ani,Tumbuhan memakai cahaya matahari.\n2202,Budi,-\n"
WIDE_MAP = {"id_col": "nim", "name_cols": ["nama"], "columns": {"Q1": {"column": "jwb"}}}


def test_preview_reads_semicolons_and_a_bom(client):
    text = "﻿nim;nama;jawaban Q1\n123;Ani;tumbuhan menggunakan cahaya\n"
    r = client.post("/api/imports/preview", files={"file": ("x.csv", text.encode("utf-8"))}).json()
    assert r["columns"] == ["nim", "nama", "jawaban Q1"] and r["count"] == 1
    assert r["rows"] == [["123", "Ani", "tumbuhan menggunakan cahaya"]]


def test_import_wide_answers_dry_run_then_for_real(client):
    course = demo_course(client)
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP, dry_run=True).json()
    assert (r["new"], r["added"], r["blank"], r["existing"]) == (1, 0, 1, [])
    assert "Q1_2201" not in db.answer_ids(["Q1"])
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP).json()
    assert r["added"] == 1 and r["answers"][0]["answer_id"] == "Q1_2201"
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP).json()
    assert r["added"] == 0 and r["existing"] == ["Q1_2201"]
    students = client.get(f"/api/courses/{course}/students").json()
    assert ["2201", "Ani", 1] in students["rows"]


def test_import_long_answers(client):
    text = "nim,soal,jawaban\n2203,Q1,Daun menyerap karbon dioksida.\n2203,Q9,lain\n"
    mapping = {"id_col": "nim", "columns": {"Q1": {"column": "jawaban", "filter_column": "soal",
                                                    "filter_value": "Q1"}}}
    r = post(client, f"/api/courses/{demo_course(client)}/answers", text, mapping).json()
    assert r["added"] == 1 and r["answers"][0]["text"] == "Daun menyerap karbon dioksida."


def test_mapping_mistakes_are_422(client):
    course = demo_course(client)
    r = post(client, f"/api/courses/{course}/answers", WIDE, {**WIDE_MAP, "columns": {"Q1": {"column": "nope"}}})
    assert r.status_code == 422 and "'nope'" in r.json()["details"][0]
    other = client.post("/api/courses", json={"code": "C2", "name": "Lain"}).json()["id"]
    r = post(client, f"/api/courses/{other}/answers", WIDE, WIDE_MAP)
    assert r.status_code == 422 and "Q1" in r.json()["details"][0]
    r = client.post(f"/api/courses/{course}/answers", files={"file": ("x.csv", WIDE.encode())},
                    data={"mapping": "{not json"})
    assert r.status_code == 422
    half = {"id_col": "nim", "columns": {"Q1": {"column": "jwb", "filter_column": "soal"}}}
    assert post(client, f"/api/courses/{course}/answers", WIDE, half).status_code == 422


def test_import_scores(client):
    course = demo_course(client)
    post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP)
    mapping = {"id_col": "nim", "question_id": "Q1", "columns": {"_total": "total"}, "rater_id": "D1"}
    r = post(client, f"/api/courses/{course}/scores", "nim,total\n2201,\"85,5\"\n", mapping).json()
    assert r["added"] == 1 and r["rows"] == [["Q1_2201", "D1", "_total", 85.5]]
    scores = db.human_scores(include_synthetic=True)
    assert scores[scores.answer_id == "Q1_2201"].score_0_100.tolist() == [85.5]
    r = post(client, f"/api/courses/{course}/scores", "nim,total\n2201,150\n", mapping)
    assert r.status_code == 422 and "outside 0-100" in r.json()["details"][0]


def test_upload_over_the_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(deps, "MAX_UPLOAD", 10)
    r = client.post("/api/imports/preview", files={"file": ("x.csv", b"a,b\n" * 10)})
    assert r.status_code == 413 and r.json()["error"] == "too_large"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_imports.py -q`
Expected: FAIL with 404s (no import routes yet).

- [ ] **Step 3: Implement**

Append to `src/autograde/api/schemas.py` (add `Field` and `model_validator` to the pydantic import):

```python
class AnswerSource(BaseModel):
    """One question's answers: a column of a wide table, or a long table's rows where filter_column == filter_value."""
    column: str
    filter_column: str | None = None
    filter_value: str | None = None

    @model_validator(mode="after")
    def _filter_pair(self):
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError("filter_column and filter_value go together")
        return self


class AnswerMapping(BaseModel):
    id_col: str
    name_cols: list[str] = []
    columns: dict[str, AnswerSource] = Field(min_length=1)
    split: Literal["pilot", "test"] = "test"

    def source_map(self):
        """importer.answers_from_table's form: qid -> (answer column, None | (question column, value))."""
        return {q: (s.column, (s.filter_column, s.filter_value) if s.filter_column else None)
                for q, s in self.columns.items()}


class ScoreMapping(BaseModel):
    id_col: str
    question_id: str
    columns: dict[str, str] = Field(min_length=1)  # criterion id, or "_total" for a holistic score -> column
    rater_id: Name = "D1"
```

`src/autograde/api/routes/imports.py`:

```python
"""LMS CSV imports: preview the columns, then import answers or lecturer scores through a column mapping
(Impor Jawaban). Stateless: the browser sends the file again with the mapping."""
import csv
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from autograde import db, importer
from autograde.api import deps
from autograde.api.schemas import AnswerMapping, ScoreMapping, table

router = APIRouter(tags=["imports"])
PREVIEW_ROWS = 5


def read_csv(file):
    """sep=None sniffs "," or ";" (spreadsheets in an Indonesian locale save with ";"); utf-8-sig strips a BOM."""
    data = deps.read_upload(file)
    try:
        return pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig", sep=None,
                           engine="python")
    except (ValueError, csv.Error) as e:
        raise HTTPException(422, f"{file.filename} is not a readable CSV ({e})") from None


def _mapping(model, text):
    try:
        return model.model_validate_json(text)
    except ValidationError as e:
        raise HTTPException(422, [f"mapping.{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]) from None


def _check_columns(df, columns):
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise HTTPException(422, [f"column {c!r} is not in the CSV" for c in missing])


def _course_questions(course_id, qids):
    known = {q for a in db.assessments(course_id) for q in db.questions(a["id"])}
    unknown = sorted(set(qids) - known)
    if unknown:
        raise HTTPException(422, [f"question {q} is not in this course" for q in unknown])


@router.post("/imports/preview")
def preview(file: UploadFile = File(...)):
    df = read_csv(file)
    return {"count": len(df), **table(df.head(PREVIEW_ROWS))}


@router.post("/courses/{course_id}/answers")
def import_answers(course_id: int, file: UploadFile = File(...), mapping: str = Form(...), dry_run: bool = False):
    deps.course_or_404(course_id)
    m = _mapping(AnswerMapping, mapping)
    _course_questions(course_id, m.columns)
    df = read_csv(file)
    _check_columns(df, [m.id_col, *m.name_cols,
                        *(c for s in m.columns.values() for c in (s.column, s.filter_column) if c)])
    rows, report = importer.answers_from_table(df, m.id_col, m.name_cols, m.source_map(), m.split)
    if rows and not dry_run:
        db.import_course_answers(course_id, rows)
    return {"new": len(rows), "added": 0 if dry_run else len(rows), "blank": report["blank"],
            "existing": report["existing"],
            "answers": [{k: r[k] for k in ("answer_id", "question_id", "external_id", "name", "text")} for r in rows]}


@router.post("/courses/{course_id}/scores")
def import_scores(course_id: int, file: UploadFile = File(...), mapping: str = Form(...), dry_run: bool = False):
    """Lecturer scores 0-100; an earlier score by the same rater for the same criterion is replaced."""
    deps.course_or_404(course_id)
    m = _mapping(ScoreMapping, mapping)
    _course_questions(course_id, [m.question_id])
    df = read_csv(file)
    _check_columns(df, [m.id_col, *m.columns.values()])
    scores = importer.scores_from_table(df, m.id_col, m.question_id, m.columns, m.rater_id)
    if len(scores) and not dry_run:
        db.add_human_scores(scores, replace=True)
    return {"added": 0 if dry_run else len(scores), **table(scores)}
```

In `src/autograde/api/app.py`:

```python
from autograde.api.routes import courses, imports, questions
```

```python
ROUTERS = [courses.router, questions.router, imports.router]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_imports.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autograde/api tests/test_api_imports.py
git commit -m "Add the CSV import routes: preview, answers and lecturer scores with a column mapping and dry run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Grading jobs and the grading routes

**Files:**
- Create: `src/autograde/api/jobs.py`
- Modify: `src/autograde/api/deps.py` (append `is_stale`)
- Modify: `src/autograde/api/schemas.py` (append the grading models)
- Modify: `src/autograde/api/app.py` (register the router)
- Create: `src/autograde/api/routes/grading.py`
- Modify: `tests/conftest.py` (`client` resets the context cache)
- Create: `tests/test_api_grading.py`

**Interfaces:**
- Consumes: `db.create_job / job / running_job / update_job / finish_job` (Task 3), `pipeline.assessment_run`, `pipeline.grade_assessment_answer(run_id, answer, contexts, use_llm_feedback)`, `pipeline.apply_corrections(run_id, answer_id) -> (ScoreResult | None, skipped)`, `grades.status_table / bulk_approvable / ready / grades_csv / feedback_csv`, `normalize.Embedder`.
- Produces:
  - `jobs.context(qid) -> pipeline.Context` (cached per `(qid, updated)`, used by Tasks 9-10), `jobs.embedder()`, `jobs.start(assessment_id, which, llm_feedback) -> job dict`, `jobs.run_job(job_id)`, `jobs.cancel(job_id) -> job dict`, `jobs.JobConflict`, `jobs.NothingToGrade`, `jobs._contexts`, `jobs._cancel`
  - `deps.is_stale(result) -> bool`
  - `schemas.GradingRequest`, `ReviewerIn`, `Correction`, `CorrectionsIn`
  - Endpoints: `GET /assessments/{id}/status`, `POST /assessments/{id}/grading`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /assessments/{id}/review/bulk`, `POST /results/{run}/{answer}/review`, `POST /results/{run}/{answer}/corrections`, `GET /assessments/{id}/exports/{grades|feedback}.csv?draft=`

- [ ] **Step 1: Reset the context cache in the `client` fixture**

In `tests/conftest.py`, inside `client`, add `from autograde.api import jobs` to its imports and this line after the `Context.load` monkeypatch:

```python
    monkeypatch.setattr(jobs, "_contexts", {})  # contexts built with the stub must not leak into other tests
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_api_grading.py`:

```python
"""Grading an assessment through the API: background jobs, review, corrections and the gated exports."""
import threading
import time

from fastapi.testclient import TestClient

from autograde import db, pipeline
from autograde.api import jobs
from autograde.api.app import create_app


def demo_assessment(client):
    course = next(c for c in client.get("/api/courses").json() if c["code"] == "DEMO")["id"]
    return client.get(f"/api/courses/{course}/assessments").json()[0]["id"]


def wait(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} is still running")


def column(status, name):
    i = status["columns"].index(name)
    return {row[0]: row[i] for row in status["rows"]}  # keyed by answer_id, the first column


def test_grade_review_correct_and_export(client):
    aid = demo_assessment(client)
    st = client.get(f"/api/assessments/{aid}/status").json()
    assert st["counts"] == {"belum dinilai": 7} and not st["ready"]
    assert set(column(st, "name").values()) == {None}  # demo answers have no student name: null, not NaN
    r = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert r.status_code == 202 and r.json()["total"] == 7
    job = wait(client, r.json()["id"])
    assert (job["status"], job["done"], job["failures"], job["current"]) == ("done", 7, [], None)
    st = client.get(f"/api/assessments/{aid}/status").json()
    run_id = st["run_id"]
    assert st["counts"] == {"dinilai": 7} and "Q1_A08" not in st["approvable"]  # A08 has a contradiction

    r = client.get(f"/api/assessments/{aid}/exports/grades.csv")
    assert r.status_code == 409 and "dinilai" in r.json()["message"]
    draft = client.get(f"/api/assessments/{aid}/exports/grades.csv?draft=true")
    assert draft.status_code == 200 and draft.text.lstrip("﻿").startswith("# DRAF")

    assert client.post(f"/api/assessments/{aid}/review/bulk", json={"by": "  "}).status_code == 422
    bulk = client.post(f"/api/assessments/{aid}/review/bulk", json={"by": "DS"}).json()["reviewed"]
    assert sorted(bulk) == sorted(st["approvable"])

    ledger = db.result(run_id, "Q1_A08")["ledger"]
    ref = next(e["reference_id"] for e in ledger if e["status"] == "CONTRADICTED")
    before = db.result(run_id, "Q1_A08")["score"]["score"]
    url = f"/api/results/{run_id}/Q1_A08"
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": "R99", "status": "MATCHED", "reason": "x"}]}).status_code == 422
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MATCHED", "reason": " "}]}).status_code == 422
    r = client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MATCHED", "reason": "dibaca ulang"}]})
    sc = r.json()["score"]
    assert r.status_code == 200 and sc["score"] > before and abs(sc["score"] - sc["sparql_score"]) < 1e-9

    for answer_id, status in column(client.get(f"/api/assessments/{aid}/status").json(), "status").items():
        if status == "dinilai":
            assert client.post(f"/api/results/{run_id}/{answer_id}/review", json={"by": "DS"}).status_code == 200
    assert client.post(f"{url}/review", json={"by": "DS"}).status_code == 409  # already reviewed
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MISSING", "reason": "x"}]}).status_code == 409
    r = client.get(f"/api/assessments/{aid}/exports/grades.csv")
    assert r.status_code == 200 and r.text.lstrip("﻿").startswith("external_id,name,Q1")
    assert 'filename="DEMO_' in r.headers["content-disposition"]
    assert client.get(f"/api/assessments/{aid}/exports/feedback.csv").status_code == 200

    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])  # the key is edited
    assert client.get(f"/api/assessments/{aid}/status").json()["counts"] == {"usang": 7}
    r = client.post(f"/api/results/{run_id}/Q1_A07/review", json={"by": "DS"})
    assert r.status_code == 409 and "grade it again" in r.json()["message"]
    job = wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "stale"}).json()["id"])
    assert job["done"] == 7 and client.get(f"/api/assessments/{aid}/status").json()["counts"] == {"dinilai": 7}
    assert client.post(f"/api/assessments/{aid}/grading", json={"which": "stale"}).status_code == 422


def test_start_returns_at_once_and_one_job_at_a_time(client, monkeypatch):
    aid = demo_assessment(client)
    gate, orig = threading.Event(), pipeline.grade_assessment_answer

    def held(run_id, answer, contexts, use_llm_feedback=False):
        gate.wait(30)
        return orig(run_id, answer, contexts, use_llm_feedback)

    monkeypatch.setattr(pipeline, "grade_assessment_answer", held)
    r = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert r.status_code == 202 and r.json()["status"] == "running"  # returned while the thread waits
    second = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert second.status_code == 409 and str(r.json()["id"]) in second.json()["message"]
    gate.set()
    assert wait(client, r.json()["id"])["status"] == "done"


def test_one_failing_answer_does_not_stop_the_class(client, monkeypatch):
    aid = demo_assessment(client)
    orig = pipeline.grade_assessment_answer

    def flaky(run_id, answer, contexts, use_llm_feedback=False):
        if answer.answer_id == "Q1_A07":
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return orig(run_id, answer, contexts, use_llm_feedback)

    monkeypatch.setattr(pipeline, "grade_assessment_answer", flaky)
    job = wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()["id"])
    assert job["status"] == "done" and job["done"] == 7
    assert job["failures"] == [{"answer_id": "Q1_A07", "error": "ANTHROPIC_API_KEY is not set"}]
    st = client.get(f"/api/assessments/{aid}/status").json()
    assert st["counts"] == {"dinilai": 6, "belum dinilai": 1}


def test_cancel(client):
    aid = demo_assessment(client)
    run_id = pipeline.assessment_run(aid)
    job_id = db.create_job(aid, run_id, "new", False, ["Q1_A07", "Q1_A08"])
    jobs._cancel[job_id] = threading.Event()
    jobs._cancel[job_id].set()
    jobs.run_job(job_id)
    j = db.job(job_id)
    assert (j["status"], j["done"]) == ("cancelled", 0) and db.result(run_id, "Q1_A07") is None
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409  # not running any more
    orphan = db.create_job(aid, run_id, "new", False, ["Q1_A07"])  # running, but no thread in this process
    assert client.post(f"/api/jobs/{orphan}/cancel").json()["status"] == "interrupted"
    assert client.get("/api/jobs/999").status_code == 404


def test_restart_marks_the_job_interrupted_and_resuming_skips_graded_answers(client):
    aid = demo_assessment(client)
    run_id = pipeline.assessment_run(aid)
    job_id = db.create_job(aid, run_id, "new", False, ["Q1_A07", "Q1_A08", "Q1_A09"])
    answers = {a.answer_id: a for a in db.assessment_answers(aid).itertuples()}
    for a in ("Q1_A07", "Q1_A08"):  # graded before the server stopped
        pipeline.grade_assessment_answer(run_id, answers[a], {"Q1": jobs.context("Q1")})
    with TestClient(create_app(), base_url="http://127.0.0.1") as restarted:
        assert restarted.get(f"/api/jobs/{job_id}").json()["status"] == "interrupted"
        r = restarted.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()
        assert r["total"] == 5 and not {"Q1_A07", "Q1_A08"} & set(r["answer_ids"])
        wait(restarted, r["id"])


def test_context_reloads_after_the_key_is_edited(client):
    first = jobs.context("Q1")
    assert jobs.context("Q1") is first
    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    assert jobs.context("Q1") is not first and len(jobs._contexts) == 1
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_grading.py -q`
Expected: FAIL with `ImportError: cannot import name 'jobs'` from `autograde.api`.

- [ ] **Step 4: Implement**

Append to `src/autograde/api/deps.py`:

```python
def is_stale(result):
    """Graded before its question's key was last edited (grades.status_table's 'usang')."""
    updated = db.question_updated([result["question_id"]]).get(result["question_id"])
    return bool(updated and result["graded"] and result["graded"] < updated)
```

Append to `src/autograde/api/schemas.py` (add `from autograde.models import Status`):

```python
class GradingRequest(BaseModel):
    which: Literal["new", "stale"] = "new"
    llm_feedback: bool = False


class ReviewerIn(BaseModel):
    by: Name


class Correction(BaseModel):
    reference_id: str
    status: Status
    reason: Name


class CorrectionsIn(BaseModel):
    by: Name
    corrections: list[Correction] = Field(min_length=1)
```

`src/autograde/api/jobs.py`:

```python
"""Background grading for the API: one job at a time in a daemon thread, progress in the job table.

Grading is resumable per answer, so a job that dies with the server is marked interrupted at the next start and is
simply started again: the status table no longer lists the answers it already graded.
"""
import logging
import threading

from autograde import db, grades, pipeline
from autograde.normalize import Embedder

log = logging.getLogger("uvicorn.error")
WANTED = {"new": "belum dinilai", "stale": "usang"}
_start_lock = threading.Lock()  # checking for a running job and inserting the new one are one step
_cancel = {}  # job id -> threading.Event, for jobs whose thread runs in this process
_contexts = {}  # (qid, question.updated) -> pipeline.Context
_embedder = None


class JobConflict(RuntimeError):
    pass


class NothingToGrade(ValueError):
    pass


def embedder():
    """One Embedder per process: the sentence-transformers model loads once, not once per question."""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def context(qid):
    """The question's grading context, keyed by its `updated` stamp: an edited key is used from the next answer on,
    instead of grading the rest of a job with the old one."""
    key = (qid, db.question_updated([qid]).get(qid))
    if key not in _contexts:
        for old in [k for k in _contexts if k[0] == qid]:
            _contexts.pop(old, None)
        _contexts[key] = pipeline.Context.load(qid, cosine=embedder().cosine)
    return _contexts[key]


def start(assessment_id, which, llm_feedback):
    run_id = pipeline.assessment_run(assessment_id)
    table = grades.status_table(assessment_id, run_id)
    ids = table[table.status == WANTED[which]].answer_id.tolist()
    if not ids:
        raise NothingToGrade(f"no answers are '{WANTED[which]}'")
    with _start_lock:
        running = db.running_job()
        if running:
            raise JobConflict(f"job {running['id']} is still grading; wait for it or cancel it")
        job_id = db.create_job(assessment_id, run_id, which, llm_feedback, ids)
        _cancel[job_id] = threading.Event()
    threading.Thread(target=run_job, args=(job_id,), name=f"grading-job-{job_id}", daemon=True).start()
    return db.job(job_id)


def run_job(job_id):
    job = db.job(job_id)
    cancel = _cancel.setdefault(job_id, threading.Event())
    try:
        answers = {a.answer_id: a for a in db.assessment_answers(job["assessment_id"]).itertuples()}
        done, failures, cancelled = 0, [], False
        for aid in job["answer_ids"]:
            if cancel.is_set():
                cancelled = True
                break
            db.update_job(job_id, aid, done, failures)
            a = answers[aid]
            try:
                pipeline.grade_assessment_answer(job["run_id"], a, {a.question_id: context(a.question_id)},
                                                 job["llm_feedback"])
            except Exception as e:  # one answer's failure (no API key, parity) must not stop the class
                log.warning("grading job %s: %s failed: %s", job_id, aid, e)
                failures.append({"answer_id": aid, "error": str(e)})
            done += 1
        db.update_job(job_id, None, done, failures)
        db.finish_run(job["run_id"])
        db.finish_job(job_id, "cancelled" if cancelled else "done")
    except Exception:  # never leave a dead job 'running': it would block every new one
        log.exception("grading job %s stopped", job_id)
        db.finish_job(job_id, "interrupted")
    finally:
        _cancel.pop(job_id, None)


def cancel(job_id):
    """Stops after the current answer: an LLM call can't be stopped halfway."""
    job = db.job(job_id)
    if job["status"] != "running":
        raise JobConflict(f"job {job_id} is {job['status']}, not running")
    event = _cancel.get(job_id)
    if event is None:  # marked running, but its thread died with an earlier server
        db.finish_job(job_id, "interrupted")
    else:
        event.set()
    return db.job(job_id)
```

`src/autograde/api/routes/grading.py`:

```python
"""Grading an assessment: background jobs, the status table, review, corrections and the CSV exports (Penilaian)."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from autograde import db, grades, importer, pipeline
from autograde.api import deps, jobs
from autograde.api.schemas import CorrectionsIn, GradingRequest, ReviewerIn, table

router = APIRouter(tags=["grading"])
EXPORT_NAMES = {"grades": "nilai", "feedback": "umpan_balik"}


def _status(assessment_id):
    deps.assessment_or_404(assessment_id)
    run_id = pipeline.assessment_run(assessment_id)
    return run_id, grades.status_table(assessment_id, run_id)


def _pending(run_id, answer_id):
    """A graded, up-to-date, unreviewed result: the only kind review and corrections accept."""
    r = deps.result_or_404(run_id, answer_id)
    if deps.is_stale(r):
        raise HTTPException(409, f"{answer_id}: its key was edited after grading; grade it again first")
    if r["reviewed"]:
        raise HTTPException(409, f"{answer_id} is already reviewed")
    return r


@router.get("/assessments/{assessment_id}/status")
def status(assessment_id: int):
    run_id, t = _status(assessment_id)
    return {"run_id": run_id, "counts": {s: int(n) for s, n in t.status.value_counts().items()},
            "approvable": grades.bulk_approvable(t), "ready": grades.ready(t),
            "synthetic": bool((t.source == "synthetic").any()), **table(t)}


@router.post("/assessments/{assessment_id}/grading", status_code=202)
def start_grading(assessment_id: int, body: GradingRequest):
    deps.assessment_or_404(assessment_id)
    try:
        return jobs.start(assessment_id, body.which, body.llm_feedback)
    except jobs.NothingToGrade as e:
        raise HTTPException(422, str(e)) from None
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e)) from None


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    j = db.job(job_id)
    if j is None:
        raise HTTPException(404, f"unknown job {job_id}")
    return j


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    get_job(job_id)
    try:
        return jobs.cancel(job_id)
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e)) from None


@router.post("/assessments/{assessment_id}/review/bulk")
def bulk_review(assessment_id: int, body: ReviewerIn):
    """Approves every graded answer with no ⚑ entry and no contradiction."""
    run_id, t = _status(assessment_id)
    ids = grades.bulk_approvable(t)
    db.mark_reviewed(run_id, ids, body.by)
    return {"reviewed": ids}


@router.post("/results/{run_id}/{answer_id}/review")
def review(run_id: str, answer_id: str, body: ReviewerIn):
    _pending(run_id, answer_id)
    db.mark_reviewed(run_id, [answer_id], body.by)
    r = db.result(run_id, answer_id)
    return {"answer_id": answer_id, "reviewed": r["reviewed"], "reviewed_by": r["reviewed_by"]}


@router.post("/results/{run_id}/{answer_id}/corrections")
def correct(run_id: str, answer_id: str, body: CorrectionsIn):
    """The lecturer's ledger corrections; the score is recomputed and checked with SPARQL."""
    r = _pending(run_id, answer_id)
    unknown = sorted({c.reference_id for c in body.corrections} - {e["reference_id"] for e in r["ledger"]})
    if unknown:
        raise HTTPException(422, [f"{x} is not in this answer's ledger" for x in unknown])
    db.add_overrides([{"answer_id": answer_id, "reference_id": c.reference_id, "status": c.status, "by": body.by,
                       "date": date.today().isoformat(), "reason": c.reason} for c in body.corrections])
    sc, skipped = pipeline.apply_corrections(run_id, answer_id)
    return {"score": sc.model_dump(), "skipped": skipped}


@router.get("/assessments/{assessment_id}/exports/{kind}.csv")
def export(assessment_id: int, kind: Literal["grades", "feedback"], draft: bool = False):
    """The final files unlock only when every answer is reviewed; drafts are always available."""
    run_id, t = _status(assessment_id)
    if t.empty:
        raise HTTPException(409, "this assessment has no answers")
    if not draft and not grades.ready(t):
        missing = t[t.status != "ditinjau"].status.value_counts()
        raise HTTPException(409, "final export locked: " + ", ".join(f"{n} {s}" for s, n in missing.items()))
    text = grades.grades_csv(t, db.questions(assessment_id), draft) if kind == "grades" \
        else grades.feedback_csv(t, run_id)
    a = db.assessment(assessment_id)
    name = f"{importer.slug(db.course(a['course_id'])['code'] + '_' + a['name'])}_{EXPORT_NAMES[kind]}" \
           f"{'_draf' if draft else ''}.csv"
    return Response(text.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
```

In `src/autograde/api/app.py`:

```python
from autograde.api.routes import courses, grading, imports, questions
```

```python
ROUTERS = [courses.router, questions.router, imports.router, grading.router]
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_grading.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autograde/api tests/conftest.py tests/test_api_grading.py
git commit -m "Add background grading jobs and the grading routes: status, review, corrections and gated exports" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Semantic Web routes: ontology, graphs, SPARQL, gold key, OWL export

**Files:**
- Modify: `src/autograde/api/schemas.py` (append `SparqlIn`)
- Modify: `src/autograde/api/app.py` (register the router)
- Create: `src/autograde/api/routes/semantic.py`
- Create: `tests/test_api_semantic.py`

**Interfaces:**
- Consumes: `io.ontology_graph`, `io.ontology_path`, `io.load_predicates`, `kg.graphs / get_graph / query / gold_graph_name / ONTOLOGY`, `kg.KGBusyError`, `rdfviz.*` (Task 2), `gold.load / criterion_weights`, `owl_export.rdfxml` (Task 4), `importer.slug`.
- Produces:
  - `schemas.SparqlIn`
  - `routes/semantic.py` with `router`, `TEMPLATES` and the endpoints `GET /ontology?lang=`, `GET /graphs`, `GET /graphs/turtle?name=`, `GET /graphs/view?name=`, `POST /sparql`, `GET /sparql/templates?scope=`, `GET /questions/{qid}/gold`, `GET /export/owl?run=&answer=`. Task 10 appends to this file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_semantic.py`:

```python
"""The Semantic Web views: ontology, named graphs, SPARQL, the gold key and the OWL export."""
from rdflib import Graph

from autograde import db, pipeline, rdfviz

GOLD = "urn:ag:gold:Q1"


def test_ontology(client):
    o = client.get("/api/ontology").json()
    assert o["graph"] == "urn:ag:ontology" and o["counts"]["swrl_rules"] == len(o["rules"]) > 0
    assert "digraph" in o["classes_dot"] and "digraph" in o["relations_dot"] and o["owl"].startswith("<?xml")
    assert o["properties"]["columns"] and o["rules"][0]["title"] and "->" in o["rules"][0]["rule"]
    ids = {p["id"] for p in client.get("/api/ontology?lang=en").json()["predicates"]}
    assert "is_a" in ids and "menggunakan" not in ids


def test_named_graphs(client):
    names = [g["name"] for g in client.get("/api/graphs").json()]
    assert "urn:ag:ontology" in names and GOLD in names
    r = client.get("/api/graphs/turtle", params={"name": GOLD})
    assert r.status_code == 200 and "ReferenceTriple" in r.text and 'filename="gold_Q1.ttl"' in r.headers["content-disposition"]
    view = client.get("/api/graphs/view", params={"name": GOLD}).json()
    assert view["graph"]["nodes"] and "triple" in view["edge_types"]
    assert client.get("/api/graphs/turtle", params={"name": "urn:ag:nope"}).status_code == 404


def test_sparql(client):
    count = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    r = client.post("/api/sparql", json={"query": count}).json()
    assert r["kind"] == "table" and r["columns"] == ["n"] and int(r["rows"][0][0]) > 0
    q = rdfviz.PREFIXES + "SELECT ?r WHERE { ?r a ag:ReferenceTriple } ORDER BY ?r"
    r = client.post("/api/sparql", json={"query": q, "graphs": [GOLD]}).json()
    assert [row[0] for row in r["rows"]] == [f"key:Q1_R{i}" for i in range(1, 6)]
    r = client.post("/api/sparql", json={"query": "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <urn:ag:gold:Q1> { ?s ?p ?o } }"})
    assert r.json()["kind"] == "turtle" and len(Graph().parse(data=r.json()["turtle"], format="turtle")) > 0
    r = client.post("/api/sparql", json={"query": "SELEKT ?x WHERE {"})
    assert r.status_code == 422 and r.json()["message"].startswith("query failed")
    r = client.post("/api/sparql", json={"query": "SELECT * WHERE { SERVICE <http://x> { ?s ?p ?o } }"})
    assert r.status_code == 422
    assert client.post("/api/sparql", json={"query": count, "graphs": ["urn:ag:nope"]}).status_code == 422


def test_sparql_templates(client):
    assert client.get("/api/sparql/templates?scope=kg").json() == rdfviz.KG_QUERIES
    assert set(client.get("/api/sparql/templates?scope=run").json()) == {*rdfviz.RUN_QUERIES, *rdfviz.ANSWER_QUERIES}


def test_gold_key(client):
    g = client.get("/api/questions/Q1/gold").json()
    assert g["graph"] == GOLD and [t["id"] for t in g["triples"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert {c["id"]: c["weight"] for c in g["criteria"]} == {"K1_Bahan": 4, "K2_Produk": 4, "K3_Energi": 2}
    assert "digraph" in g["concept_dot"] and "ReferenceTriple" in g["turtle"]
    assert client.get("/api/questions/Q404/gold").status_code == 404


def test_owl_export(client):
    ctx = pipeline.Context.load("Q1")
    text = db.answers(include_synthetic=True).set_index("answer_id").text["Q1_A07"]
    pipeline.run_answer(ctx, "Q1_A07", text, "gold", pipeline.ui_run(), use_llm_feedback=False)
    r = client.get("/api/export/owl", params={"run": "ui", "answer": "Q1_A07"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/rdf+xml")
    assert 'filename="autograde-ui-Q1_A07.owl"' in r.headers["content-disposition"]
    assert len(Graph().parse(data=r.content, format="xml")) > 0
    assert client.get("/api/export/owl", params={"run": "nope"}).status_code == 404
    assert client.get("/api/export/owl", params={"run": "ui", "answer": "Q1_A01"}).status_code == 404
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_semantic.py -q`
Expected: FAIL with 404s (no semantic routes yet).

- [ ] **Step 3: Implement**

Append to `src/autograde/api/schemas.py`:

```python
class SparqlIn(BaseModel):
    query: str = Field(min_length=1)
    graphs: list[str] | None = None  # named graphs (plus the ontology) queried with rdflib; None: the whole store
```

`src/autograde/api/routes/semantic.py`:

```python
"""The Semantic Web views: ontology, named graphs, SPARQL, the gold key, graded answers and the OWL export
(Ontologi, Soal & Kunci, Nilai Jawaban, Konsol SPARQL, Penjelajah Graf, Graf Pengetahuan)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from rdflib import OWL, RDF, Namespace

from autograde import gold, importer, io, kg, owl_export, rdfviz
from autograde.api import deps
from autograde.api.schemas import SparqlIn, table

router = APIRouter(tags=["semantic"])
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
TEMPLATES = {"answer": rdfviz.ANSWER_QUERIES, "run": {**rdfviz.RUN_QUERIES, **rdfviz.ANSWER_QUERIES},
             "kg": rdfviz.KG_QUERIES}


def _graph_name(name):
    if name not in {g["name"] for g in kg.graphs()}:
        raise HTTPException(404, f"no named graph {name}")
    return name


def _rules():
    rules = []
    for block in (io.ROOT / "ontology" / "rules.swrl.txt").read_text(encoding="utf-8").strip().split("\n\n"):
        title, rule = block.split("\n", 1)
        rules.append({"title": title.lstrip("# "), "rule": rule})
    return rules


@router.get("/ontology")
def ontology(lang: Literal["all", "id", "en"] = "all"):
    g = io.ontology_graph()
    preds = io.load_predicates()["predicates"]
    only = None if lang == "all" else {p["id"] for p in preds if p.get("lang") == lang}
    return {"graph": kg.ONTOLOGY,
            "counts": {"classes": sum(1 for x in g.subjects(RDF.type, OWL.Class) if str(x).startswith(str(io.AG))),
                       "object_properties": len(set(g.subjects(RDF.type, OWL.ObjectProperty))),
                       "data_properties": len(set(g.subjects(RDF.type, OWL.DatatypeProperty))),
                       "relations": len(set(g.subjects(RDF.type, io.AG.Relation))),
                       "swrl_rules": len(set(g.subjects(RDF.type, SWRL.Imp)))},
            "classes_dot": rdfviz.ontology_classes_dot(g),
            "properties": table(rdfviz.properties_table(g)),
            "relations_dot": rdfviz.relations_dot(g, only),
            "predicates": [p for p in preds if only is None or p["id"] in only],
            "rules": _rules(),
            "owl": io.ontology_path().read_text(encoding="utf-8")}


@router.get("/graphs")
def graphs():
    return kg.graphs()


@router.get("/graphs/turtle")
def graph_turtle(name: str):
    ttl = kg.get_graph(_graph_name(name)).serialize(format="turtle")
    return Response(ttl, media_type="text/turtle; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{rdfviz.turtle_file_name(name)}"'})


@router.get("/graphs/view")
def graph_view(name: str):
    return {"graph": rdfviz.vis_graph(kg.get_graph(_graph_name(name))), "node_types": rdfviz.VIS_NODE_TYPES,
            "edge_types": rdfviz.VIS_EDGE_TYPES}


@router.post("/sparql")
def sparql(body: SparqlIn):
    """Read-only: SERVICE is refused and updates don't parse."""
    if body.graphs:
        known = {g["name"] for g in kg.graphs()}
        missing = [n for n in body.graphs if n not in known]
        if missing:
            raise HTTPException(422, [f"no named graph {n}" for n in missing])
    try:
        if body.graphs:
            result = rdfviz.run_query(rdfviz.merged_graph(body.graphs), body.query)
        else:
            result = kg.query(body.query)
            if not isinstance(result, str):
                result = result.map(lambda v: rdfviz.short(v) if isinstance(v, str) else v)
    except kg.KGBusyError:
        raise
    except Exception as e:  # a syntax or evaluation error is the user's query, not the server's fault
        raise HTTPException(422, f"query failed: {e}") from None
    if isinstance(result, str):
        return {"kind": "turtle", "turtle": result}
    return {"kind": "table", **table(result)}


@router.get("/sparql/templates")
def templates(scope: Literal["answer", "run", "kg"] = "kg"):
    return TEMPLATES[scope]


@router.get("/questions/{qid}/gold")
def gold_key(qid: str):
    q = deps.question_or_404(qid)
    gold_raw, rubric, refs = gold.load(qid)
    weights = gold.criterion_weights(refs)
    name = kg.gold_graph_name(qid)
    return {"graph": name, "prompt": q["prompt"], "reference_answer": q["reference_answer"],
            "language": rubric.get("language", "id"), "validated_by": gold_raw.get("validated_by"),
            "drafted_by": gold_raw.get("drafted_by"),
            "criteria": [{**c, "weight": weights.get(c["id"], 0)} for c in rubric["criteria"]],
            "triples": [r.model_dump() for r in refs],
            "concepts": [{"concept": c, "aliases": (v or {}).get("aliases", []), "broader": (v or {}).get("broader") or []}
                         for c, v in gold_raw["concepts"].items()],
            "concept_dot": rdfviz.gold_concept_dot(refs, gold_raw["concepts"]),
            "reified_dot": rdfviz.gold_reified_dot(qid, refs),
            "turtle": kg.get_graph(name).serialize(format="turtle")}


@router.get("/export/owl")
def export_owl(run: str, answer: str | None = None):
    try:
        data = owl_export.rdfxml(run, answer)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    name = f"autograde-{importer.slug(run)}" + (f"-{importer.slug(answer)}" if answer else "") + ".owl"
    return Response(data, media_type="application/rdf+xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
```

In `src/autograde/api/app.py`:

```python
from autograde.api.routes import courses, grading, imports, questions, semantic
```

```python
ROUTERS = [courses.router, questions.router, imports.router, grading.router, semantic.router]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_semantic.py -q`
Expected: all PASS. If `test_gold_key`'s weight dict differs, check `data/questions/Q1/gold.yaml` (each triple weighs 2: K1 has R2 and R3, K2 has R4 and R5, K3 has R1) and fix the test only if the YAML changed.

- [ ] **Step 5: Commit**

```bash
git add src/autograde/api tests/test_api_semantic.py
git commit -m "Add the Semantic Web routes: ontology, named graphs, SPARQL and templates, gold key and OWL export" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Semantic Web routes: grade one answer, results, answer views, explorer

**Files:**
- Modify: `src/autograde/api/schemas.py` (append `TryIn`)
- Modify: `src/autograde/api/routes/semantic.py` (append)
- Create: `tests/test_api_results.py`

**Interfaces:**
- Consumes: `jobs.context(qid)` (Task 8), `deps.result_or_404`, `deps.run_or_404`, `pipeline.run_answer / ui_run / UI_RUN / completed_runs`, `explorer.build / load_answer / NODE_TYPES / EDGE_TYPES`, `rdfviz.alignment_dot / sigma_table / pellet_dots / answer_graph_names / short`, `ledger.recompute_rows / RECOMPUTE_QUERY`, `evaluate.human_totals`, `baselines.b1_keyword`, `feedback.triple_label`, `llm.LLMUnavailable` (mapped to 400 in Task 5).
- Produces:
  - `schemas.TryIn`
  - In `routes/semantic.py`: `human_totals(ctx) -> {answer_id: float}`, `result_view(run_id, answer_id) -> dict`, and the endpoints `GET /questions/{qid}/answers`, `POST /questions/{qid}/try`, `GET /results/{run}/{answer}`, `GET /results/{run}/{answer}/views/{graph|alignment|reasoning}`, `GET /questions/{qid}/explorer?run=&answers=`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_results.py`:

```python
"""Grading one answer on the Nilai demo, its result with the SPARQL evidence, its views and the explorer."""
import copy

from autograde import db, importer


def test_answers_of_a_question(client):
    t = client.get("/api/questions/Q1/answers").json()
    i, h = t["columns"].index("answer_id"), t["columns"].index("human")
    rows = {r[i]: r for r in t["rows"]}
    assert "Q1_A07" in rows and rows["Q1_A07"][h] is not None  # the demo has lecturer scores for A07


def test_try_a_stored_answer_and_read_its_result(client):
    r = client.post("/api/questions/Q1/try", json={"answer_id": "Q1_A08", "mode": "gold"})
    assert r.status_code == 200
    res = r.json()
    assert res["run_id"] == "ui" and res["recompute"]["ok"] and res["recompute"]["rows"]
    assert "CONTRADICTED" in [e["status"] for e in res["ledger"]] and res["ledger"][0]["reference"]
    assert isinstance(res["baseline_b1"], float) and res["graphs"][0] == "urn:ag:gold:Q1"
    again = client.get("/api/results/ui/Q1_A08").json()
    assert again["score"] == res["score"] and "baseline_b1" not in again
    assert client.get("/api/results/ui/Q1_A01").status_code == 404


def test_try_rejects_bad_requests(client):
    assert client.post("/api/questions/Q1/try", json={"text": "Tumbuhan butuh cahaya.", "mode": "gold"}).status_code == 422
    both = {"answer_id": "Q1_A08", "text": "x", "mode": "gold"}
    assert client.post("/api/questions/Q1/try", json=both).status_code == 422
    assert client.post("/api/questions/Q1/try", json={"mode": "gold"}).status_code == 422
    assert client.post("/api/questions/Q1/try", json={"answer_id": "nope", "mode": "gold"}).status_code == 422
    assert client.post("/api/questions/Q404/try", json={"text": "x"}).status_code == 404


def test_llm_mode_without_a_key_is_400(client):
    r = client.post("/api/questions/Q1/try", json={"text": "Uji tanpa kunci API 4f1c: tumbuhan menyerap air.",
                                                   "mode": "llm"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["message"]


def test_answer_views(client):
    client.post("/api/questions/Q1/try", json={"answer_id": "Q1_A08", "mode": "gold"})
    g = client.get("/api/results/ui/Q1_A08/views/graph").json()
    assert g["graph"]["nodes"] and "inferred" in g["edge_types"]
    assert "digraph" in client.get("/api/results/ui/Q1_A08/views/alignment").json()["dot"]
    r = client.get("/api/results/ui/Q1_A08/views/reasoning").json()
    assert r["contradictions"] and r["pellet"]["before"] and r["pellet"]["after"] and r["sigma"]["rows"]
    assert client.get("/api/results/ui/Q1_A08/views/nope").status_code == 422


def test_a_view_the_current_key_cannot_draw_is_409(client):
    client.post("/api/questions/Q1/try", json={"answer_id": "Q1_A08", "mode": "gold"})
    q = db.question("Q1")
    g = copy.deepcopy(q["gold"])
    g["triples"].append({"id": "R6", "s": ["Tumbuhan"], "p": "menyerap", "o": "Air", "criterion": "K1_Bahan",
                         "weight": 1})
    importer.save_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], g)
    r = client.get("/api/results/ui/Q1_A08/views/reasoning")
    assert r.status_code == 409 and "grade it again" in r.json()["message"]
    assert client.get("/api/results/ui/Q1_A08").status_code == 200  # the stored result itself still reads


def test_explorer(client):
    client.post("/api/questions/Q1/try", json={"answer_id": "Q1_A08", "mode": "gold"})
    e = client.get("/api/questions/Q1/explorer").json()
    assert {"run_id": "ui", "answers": ["Q1_A08"]} in e["sources"] and e["graph"]["nodes"]
    with_answer = client.get("/api/questions/Q1/explorer", params={"run": "ui", "answers": "Q1_A08"}).json()
    assert len(with_answer["graph"]["nodes"]) > len(e["graph"]["nodes"])
    assert client.get("/api/questions/Q1/explorer", params={"run": "ui", "answers": "Q1_A01"}).status_code == 404
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `conda run -n semantic_web pytest tests/test_api_results.py -q`
Expected: FAIL with 404s and 405s (routes missing).

- [ ] **Step 3: Implement**

Append to `src/autograde/api/schemas.py`:

```python
class TryIn(BaseModel):
    answer_id: str | None = None  # a stored answer of this question...
    text: str | None = None  # ...or a pasted one, graded as <qid>_UI
    mode: Literal["gold", "llm"] = "llm"
    llm_feedback: bool = False

    @model_validator(mode="after")
    def _one_source(self):
        if (self.answer_id is None) == (self.text is None or not self.text.strip()):
            raise ValueError("give answer_id or text, not both")
        return self
```

In `src/autograde/api/routes/semantic.py`, extend the imports:

```python
from autograde import baselines, db, evaluate, explorer, feedback, gold, importer, io, kg, ledger, owl_export, \
    pipeline, rdfviz
from autograde.api import deps, jobs
from autograde.api.schemas import SparqlIn, TryIn, table
```

and append:

```python
OLD_KEY = "graded with an older version of the key that this view can't draw; grade it again"


def human_totals(ctx):
    """Lecturer totals (0-100) of the question's answers, shown in the answer list and the explorer."""
    scores = db.human_scores(include_synthetic=True)
    sub = scores[scores.answer_id.isin(list(db.answer_ids([ctx.qid])))]
    if sub.empty:
        return {}
    try:
        return evaluate.human_totals(sub, {ctx.qid: gold.criterion_weights(ctx.refs)},
                                     dict.fromkeys(sub.answer_id.unique(), ctx.qid)).to_dict()
    except ValueError:  # scores for only some criteria: no total
        return {}


def result_view(run_id, answer_id):
    r = deps.result_or_404(run_id, answer_id)
    qid, params = r["question_id"], db.run(run_id)["params"]
    gold_name, answer_name, ledger_name = rdfviz.answer_graph_names(qid, run_id, answer_id)
    rows = ledger.recompute_rows(kg.get_graph(ledger_name), kg.get_graph(gold_name), params["lambda"])
    refs = {x.id: x for x in gold.load(qid)[2]}

    def labelled(entries):  # reference None: the triple is no longer in the key
        return entries and [{**e, "reference": feedback.triple_label(refs[e["reference_id"]])
                             if e["reference_id"] in refs else None} for e in entries]

    sc = r["score"]
    return {"run_id": run_id, "answer_id": answer_id, "question_id": qid, "graded": r["graded"],
            "reviewed": r["reviewed"], "reviewed_by": r["reviewed_by"], "stale": deps.is_stale(r),
            "score": sc, "score_corrected": r["score_corrected"],
            "recompute": {"query": ledger.RECOMPUTE_QUERY.strip(), "graphs": [ledger_name, gold_name],
                          "rows": [{"answer": rdfviz.short(x.ans), "raw": float(x.raw.toPython())} for x in rows],
                          "python": sc["score"], "sparql": sc["sparql_score"],
                          "ok": sc["sparql_score"] is not None and abs(sc["score"] - sc["sparql_score"]) < 1e-9},
            "ledger": labelled(r["ledger"]), "ledger_corrected": labelled(r["ledger_corrected"]),
            "feedback": r["feedback"], "sentences": r["sentences"], "students": r["students"],
            "extraction_log": r["extraction_log"], "graphs": [gold_name, answer_name, ledger_name]}


@router.get("/questions/{qid}/answers")
def question_answers(qid: str):
    deps.question_or_404(qid)
    df = db.answers(include_synthetic=True)
    df = df[df.question_id == qid].drop(columns=["question_id"])
    df["human"] = df.answer_id.map(human_totals(jobs.context(qid)))
    return table(df)


@router.post("/questions/{qid}/try")
def try_answer(qid: str, body: TryIn):
    """Grades one stored or pasted answer now, in the app's UI run (the Nilai demo)."""
    deps.question_or_404(qid)
    ctx = jobs.context(qid)
    if body.answer_id:
        answers = db.answers(include_synthetic=True).set_index("answer_id")
        if body.answer_id not in answers.index or answers.question_id[body.answer_id] != qid:
            raise HTTPException(422, f"{body.answer_id} is not an answer to {qid}")
        answer_id, text = body.answer_id, answers.text[body.answer_id]
    else:
        answer_id, text = f"{qid}_UI", body.text
    if body.mode == "gold" and db.annotation(answer_id) is None:
        raise HTTPException(422, f"{answer_id} has no triple annotation; use mode llm")
    pipeline.run_answer(ctx, answer_id, text, body.mode, pipeline.ui_run(), body.llm_feedback)
    return {**result_view(pipeline.UI_RUN, answer_id),
            "baseline_b1": float(baselines.b1_keyword(text, ctx.refs, ctx.gold_raw["concepts"]))}


@router.get("/results/{run_id}/{answer_id}")
def get_result(run_id: str, answer_id: str):
    return result_view(run_id, answer_id)


@router.get("/results/{run_id}/{answer_id}/views/{view}")
def result_views(run_id: str, answer_id: str, view: Literal["graph", "alignment", "reasoning"]):
    r = deps.result_or_404(run_id, answer_id)
    qid, params = r["question_id"], db.run(run_id)["params"]
    ctx, a = jobs.context(qid), explorer.load_answer(run_id, answer_id)
    trace = {"sigmas": a["sigmas"], "aligned": sorted(a["aligned"]), "contradictions": sorted(a["contradictions"])}
    try:  # a KeyError here means the key gained a reference triple this answer was never matched against
        if view == "graph":
            return {"graph": explorer.build(ctx, [a], params, human_totals(ctx)), "node_types": explorer.NODE_TYPES,
                    "edge_types": explorer.EDGE_TYPES}
        if view == "alignment":
            return {"dot": rdfviz.alignment_dot(ctx.refs, a["students"], a["entries"], trace),
                    "graph": kg.answer_graph_name(run_id, answer_id, "answer")}
        sigma = rdfviz.sigma_table(ctx.refs, a["students"], a["sigmas"]).reset_index(names="triple") \
            if a["students"] else None
    except KeyError:
        raise HTTPException(409, f"{answer_id}: {OLD_KEY}") from None
    pellet = None
    if a["aligned"]:
        _, eq, inc = io.ontology_relations()
        g = kg.get_graph(kg.answer_graph_name(run_id, answer_id, "answer"), kg.gold_graph_name(qid))
        before, after = rdfviz.pellet_dots(g, eq, inc)
        pellet = {"before": before, "after": after}
    return {"params": params, "students": [t.model_dump() for t in a["students"]],
            "sigma": None if sigma is None else table(sigma), "aligned": trace["aligned"],
            "contradictions": trace["contradictions"], "pellet": pellet, "extraction_log": r["extraction_log"]}


@router.get("/questions/{qid}/explorer")
def explorer_view(qid: str, run: str | None = None, answers: str = ""):
    """The question's knowledge graph; with a run, plus the chosen answers (default: its first 12)."""
    deps.question_or_404(qid)
    ctx = jobs.context(qid)
    sources = [{"run_id": r["run_id"], "answers": ids} for r in pipeline.completed_runs()
               if (ids := db.result_ids(r["run_id"], qid))]
    if ui := db.result_ids(pipeline.UI_RUN, qid):
        sources.append({"run_id": pipeline.UI_RUN, "answers": ui})
    chosen, params = [], ctx.params
    if run:
        params = deps.run_or_404(run)["params"]
        graded = db.result_ids(run, qid)
        ids = [x for x in answers.split(",") if x] or graded[:12]
        missing = sorted(set(ids) - set(graded))
        if missing:
            raise HTTPException(404, f"not graded in run {run}: {', '.join(missing)}")
        chosen = [explorer.load_answer(run, x) for x in ids]
    try:
        graph = explorer.build(ctx, chosen, params, human_totals(ctx))
    except KeyError:
        raise HTTPException(409, f"an answer was {OLD_KEY}") from None
    return {"sources": sources, "graph": graph, "node_types": explorer.NODE_TYPES, "edge_types": explorer.EDGE_TYPES}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `conda run -n semantic_web pytest tests/test_api_results.py -q`
Expected: all PASS.

If `test_a_view_the_current_key_cannot_draw_is_409` fails at `save_question` with a validation error about R6, the new triple clashes with the key's rules. Change R6 to another valid triple that adds a new reference id (e.g. `"s": ["Fotosintesis"], "p": "menggunakan", "o": "Cahaya", "criterion": "K3_Energi"`). Keep the point of the test: a reference id the answer was never matched against.

- [ ] **Step 5: Commit**

```bash
git add src/autograde/api tests/test_api_results.py
git commit -m "Add single-answer grading, result details with SPARQL evidence, answer views and the explorer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Read-only research routes, README API overview, full check

**Files:**
- Create: `src/autograde/api/routes/research.py`
- Modify: `src/autograde/api/app.py` (register the router)
- Create: `tests/test_api_research.py`
- Modify: `README.md` (new section "API")

**Interfaces:**
- Consumes: `db.runs / run / result_ids`, `evaluate.report_dir(run_id)`, `deps.run_or_404`.
- Produces: `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/figures/{name}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_research.py`:

```python
"""Research results are read-only: runs, evaluation reports and their figures (made by the CLI)."""
from autograde import db, evaluate


def test_runs_reports_and_figures(client, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "report_dir", lambda run_id: tmp_path / run_id)
    db.create_run("r-eval", "gold", "test", "all", {"tau_h": 0.8}, True, "sparql", False)
    db.finish_run("r-eval")
    db.save_evaluation("r-eval", "# Evaluasi\n\nICC = 0.9")
    (tmp_path / "r-eval").mkdir()
    (tmp_path / "r-eval" / "scatter.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "secret.txt").write_text("no")
    runs = {r["run_id"]: r for r in client.get("/api/runs").json()}
    assert runs["r-eval"]["has_evaluation"] and "evaluation_md" not in runs["r-eval"]
    r = client.get("/api/runs/r-eval").json()
    assert r["evaluation_md"].startswith("# Evaluasi") and r["figures"] == ["scatter.png"] and r["results"] == 0
    f = client.get("/api/runs/r-eval/figures/scatter.png")
    assert f.status_code == 200 and f.headers["content-type"] == "image/png"
    assert client.get("/api/runs/r-eval/figures/..%2Fsecret.txt").status_code == 404
    assert client.get("/api/runs/r-eval/figures/per_criterion.png").status_code == 404
    assert client.get("/api/runs/nope").status_code == 404
```

- [ ] **Step 2: Run the test to see it fail**

Run: `conda run -n semantic_web pytest tests/test_api_research.py -q`
Expected: FAIL with 404 on `/api/runs`.

- [ ] **Step 3: Implement**

`src/autograde/api/routes/research.py`:

```python
"""Research results, read-only: runs, their evaluation reports and figures. Calibration, research runs and evaluate
stay CLI commands (Evaluasi)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from autograde import db, evaluate
from autograde.api import deps

router = APIRouter(tags=["research"])


def _figures(run_id):
    d = evaluate.report_dir(run_id)
    return sorted(p.name for p in d.glob("*.png")) if d.is_dir() else []


@router.get("/runs")
def runs():
    """Newest first; the report text is left out of the list."""
    return [{**{k: v for k, v in r.items() if k != "evaluation_md"}, "has_evaluation": bool(r["evaluation_md"]),
             "results": len(db.result_ids(r["run_id"]))} for r in db.runs(finished_only=False)]


@router.get("/runs/{run_id}")
def run(run_id: str):
    return {**deps.run_or_404(run_id), "results": len(db.result_ids(run_id)), "figures": _figures(run_id)}


@router.get("/runs/{run_id}/figures/{name}")
def figure(run_id: str, name: str):
    deps.run_or_404(run_id)
    if name not in _figures(run_id):  # only names listed in the report folder, so no path can leave it
        raise HTTPException(404, f"no figure {name} for run {run_id}")
    return FileResponse(evaluate.report_dir(run_id) / name, media_type="image/png")
```

In `src/autograde/api/app.py`:

```python
from autograde.api.routes import courses, grading, imports, questions, research, semantic
```

```python
ROUTERS = [courses.router, questions.router, imports.router, grading.router, semantic.router, research.router]
```

- [ ] **Step 4: Run the test to see it pass**

Run: `conda run -n semantic_web pytest tests/test_api_research.py -q`
Expected: PASS.

- [ ] **Step 5: Add the API overview to `README.md`**

Insert before the `## Open in Protégé` section:

```markdown
## API

`python -m autograde serve` runs everything on `http://127.0.0.1:8000`: the JSON API under `/api` (try it at `/docs`) and the web pages from `web/`. It only listens on this machine and has no login. Writes from other web origins are refused. Grading an assessment runs in the background, one job at a time; closing the browser doesn't stop it, and a job cut off by a server restart is marked *interrupted* and carries on where it stopped when started again.

| Area | Endpoints |
|---|---|
| Courses | `GET/POST /courses`, `GET/POST /courses/{id}/assessments`, `GET /courses/{id}/students` |
| Questions | `GET /questions`, `GET /assessments/{id}/questions`, `GET /questions/{qid}`, `POST /questions`, `PUT /questions/{qid}`, `POST /questions/preview`, `POST /assessments/{id}/questions/upload`, `GET /questions/{qid}/files.zip`, `GET /predicates` |
| Imports | `POST /imports/preview`, `POST /courses/{id}/answers`, `POST /courses/{id}/scores` (CSV + a JSON column mapping, `?dry_run=true` to check first) |
| Grading | `GET /assessments/{id}/status`, `POST /assessments/{id}/grading`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /assessments/{id}/review/bulk`, `POST /results/{run}/{answer}/review`, `POST /results/{run}/{answer}/corrections`, `GET /assessments/{id}/exports/{grades,feedback}.csv` |
| Semantic Web | `GET /ontology`, `GET /graphs`, `GET /graphs/turtle?name=`, `GET /graphs/view?name=`, `POST /sparql`, `GET /sparql/templates`, `GET /questions/{qid}/gold`, `GET /questions/{qid}/answers`, `POST /questions/{qid}/try`, `GET /results/{run}/{answer}`, `GET /results/{run}/{answer}/views/{graph,alignment,reasoning}`, `GET /questions/{qid}/explorer`, `GET /export/owl` |
| Research (read-only) | `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/figures/{name}` |
```

- [ ] **Step 6: Run the whole suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all PASS (Pellet-marked tests skipped when Java is missing). If Java is installed, the Pellet and HermiT export tests from Task 4 and the concurrency test from Task 1 run too.

- [ ] **Step 7: Smoke-test the real server**

Run in the background: `conda run -n semantic_web python -m autograde serve --port 8765`, then:

```bash
curl -s http://127.0.0.1:8765/api/courses
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Origin: http://evil.example" -H "Content-Type: application/json" -d '{"code":"X","name":"x"}' http://127.0.0.1:8765/api/courses
```

Expected: a JSON list of courses, `200`, `403`. Stop the server afterwards.

- [ ] **Step 8: Commit**

```bash
git add src/autograde/api tests/test_api_research.py README.md
git commit -m "Add the read-only research routes and document the API" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
