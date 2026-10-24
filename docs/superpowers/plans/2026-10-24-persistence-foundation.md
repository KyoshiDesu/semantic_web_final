# Persistence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move AutoGrade-RDF from files (`data/` YAML/CSV, `outputs/runs/` JSON/TTL) to SQLite + an embedded Oxigraph triple store, drop the SAF dataset, and make the knowledge graph, Pellet's inferences and the SPARQL audit visible in the Streamlit app.

**Architecture:** Two new storage modules sit behind the existing seams: `db.py` (stdlib `sqlite3`, records with JSON columns) and `kg.py` (`pyoxigraph`, one named graph per document). `importer.py` loads `data/` once; after that every reader and writer (pipeline, CLI, evaluate, app) goes through `db`/`kg`. Scoring code (match, reason, score, feedback) does not change: it still computes in memory with rdflib, and only the persistence at the end of each answer changes.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `pyoxigraph==0.5.13`, rdflib 7.6, pandas, Streamlit 1.66, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-persistence-foundation-design.md`

## Global Constraints

- The score formulas, `config/frozen.yaml`, and the Agent Rules in `PROTOTYPE_PLAN.md` Section 1 do not change. Corrected scores never feed `evaluate`.
- Stores live in `<project root>/db/` (`db/autograde.sqlite`, `db/kg/`), overridable with the environment variable `AUTOGRADE_DB_DIR`. `db/` is gitignored.
- `importer.py` is the only module that reads `data/` after this plan.
- Files that stay files: `config/*.yaml`, `ontology/`, `outputs/cache/`, `outputs/extract/`, `docs/gold_<qid>_review.md`. Evaluation figures and CSVs go to `outputs/reports/<run_id>/`.
- Named graphs: `urn:ag:ontology`, `urn:ag:gold:<qid>`, `urn:ag:run:<run_id>:<answer_id>:{answer|ledger|ledger_corrected}`.
- Never keep a `pyoxigraph.Store` (or a query result) beyond one function call: RocksDB holds a process lock until every reference is gone.
- Keep Indonesian in UI text and data, English in code, identifiers and comments (Agent Rule 9).
- Synthetic rows keep `source = 'synthetic'`; reports that include them stay stamped "SYNTHETIC DATA" (Agent Rule 4).
- Run the suite with `conda run -n semantic_web pytest` (offline). The baseline before Task 1 is 147 passed.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on branch `persistence-foundation`.

## Review Focus

1. **A pasted answer on the Grade page** (id `Q1_UI`, no `answer` row) must still save its result: `result.answer_id` has no foreign key. Pinned in Task 2 (`test_runs_results_and_resume_guard`).
2. **The app and the CLI at the same time.** The second process must get the clear "in use by another process" message after about 2 s, and no kg call may leak a store reference that keeps the lock. Pinned in Task 3 (`test_lock_is_reported_after_retry`, `test_calls_do_not_leak_the_store`).
3. **A run interrupted mid-way** (Ctrl-C, crash, parity error) must resume without re-grading finished answers, and an unfinished run must not appear among completed runs. Pinned in Task 6 (`test_resume_grades_each_answer_once`, `test_parity_failure_raises_and_stores_nothing`, `test_completed_runs_lists_only_finished`).
4. **No database, or a database from an older schema:** commands must stop with "run `python -m autograde db import`" (or `--replace`), not a traceback. Pinned in Task 2 (`test_missing_database_is_reported`, `test_schema_version_mismatch`) and Task 4 (`test_cli_without_database_exits_with_hint`).
5. **`db import --replace` with broken data** must leave the existing database untouched, because everything is validated before anything is deleted. Pinned in Task 4 (`test_invalid_data_aborts_before_touching_the_database`).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/autograde/schema.sql` | create | `CREATE TABLE` statements (version 1) |
| `src/autograde/db.py` | create | SQLite connection, schema version, one function per read/write |
| `src/autograde/kg.py` | create | Oxigraph store: named graphs, read-only SPARQL, ontology sync, lock retry |
| `src/autograde/importer.py` | create | validate `data/` and load it into both stores |
| `src/autograde/io.py` | modify | drop SAF; answers/scores/question ids come from `db` |
| `src/autograde/gold.py` | modify | key from `db`; gold graph into `kg` |
| `src/autograde/extract.py` | modify | `extract_gold` takes an annotation dict (default: from `db`) |
| `src/autograde/ledger.py` | modify | no file writing; recompute takes rdflib graphs |
| `src/autograde/pipeline.py` | modify | results into `db`/`kg`; resumable runs; `ui` run |
| `src/autograde/evaluate.py` | modify | read runs from `db`; report text into `db`, figures into `outputs/reports/` |
| `src/autograde/cli.py` | modify | drop SAF flags; `db init|import`; `audit-import`; DB-backed recompute/override |
| `app/explorer.py` | modify | `load_answer(run_id, answer_id)`; `build` takes loaded answers; `html` takes legend types |
| `app/rdfviz.py` | modify | graph-name helpers; KG presets; generic RDF graph view; Pellet before/after DOT |
| `app/streamlit_app.py` | modify | DB-backed pages; Knowledge Graph page; parity evidence; Pellet view |
| `tests/conftest.py` | modify | session test DB imported from `data/`; `fresh_db` fixture |
| `tests/test_db.py`, `test_kg.py`, `test_importer.py`, `test_cli.py`, `test_rdfviz.py`, `test_no_file_reads.py` | create | see tasks |
| SAF files | delete | `data/external/saf/`, `data/questions/SAF_*`, `docs/gold_SAF_*_review.md`, `scripts/import_saf.py`, `tests/test_saf.py` |

---

### Task 1: Remove the SAF dataset

**Files:**
- Delete: `data/external/saf/`, `data/questions/SAF_*/`, `docs/gold_SAF_*_review.md`, `scripts/import_saf.py`, `tests/test_saf.py`
- Modify: `src/autograde/io.py`, `src/autograde/pipeline.py`, `src/autograde/cli.py`, `src/autograde/evaluate.py`, `src/autograde/normalize.py:12`, `config/predicates.yaml:3,23`, `ontology/build_ontology.py:16`, `app/streamlit_app.py`
- Modify tests: `tests/test_explorer.py`, `tests/test_app.py`, `tests/test_evaluate.py`, `tests/test_extract.py`
- Modify docs: `docs/DECISIONS.md`, `README.md`

**Interfaces:**
- Produces: `io.load_answers(include_synthetic=False)`, `io.load_human_scores(include_synthetic=False)`, `pipeline.run_split(question, mode, split, include_synthetic=False, use_llm_feedback=True, answer_ids=None, run_id=None)`. No `include_saf` anywhere.

- [ ] **Step 1: Move the two generic SAF tests to their new homes, and switch the contradiction tests to Q1_A08**

Append to `tests/test_evaluate.py`:

```python
def test_holistic_total_used_directly():
    scores = pd.DataFrame({"answer_id": ["A"], "rater_id": ["R"], "criterion": [io.TOTAL], "score_0_100": [75.0]})
    assert evaluate.human_totals(scores, {"Q": {"K1": 1}}, {"A": "Q"})["A"] == 75.0
```

Append to `tests/test_extract.py` (add `import json` and `from autograde import llm` at the top if missing):

```python
def test_english_extraction_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "cache_dir", lambda: tmp_path)
    seen = {}

    def backend(system, user, schema, cfg):
        seen.update(system=system, user=user, enum=schema["properties"]["triples"]["items"]["properties"]["predicate"]["enum"])
        return json.dumps({"triples": [{"sentence_ids": ["S1"], "subject": "diameter", "predicate": "shrinks",
                                        "object": "factor of 10", "negated": False}]})
    kept, _ = extract.extract_llm("X_A1", [("X_A1_s1", "The diameter shrinks by a factor of 10.")],
                                  backend=backend, language="en")
    assert "written in English" in seen["system"] and "UDP is a transport protocol" in seen["user"]
    assert "lacks" in seen["enum"] and "menggunakan" not in seen["enum"] and "other" in seen["enum"]
    assert kept[0].p == "decreases"
```

In `tests/test_explorer.py`, replace `test_contradiction_edge_and_reasoning` with:

```python
def test_contradiction_edge_and_reasoning(tmp_path):
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text["Q1_A08"]
    ctx, d = graded(tmp_path, "Q1", "Q1_A08", text)
    g = explorer.build(ctx, [d], ctx.params)
    kinds = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("ans:Q1_A08_t4", "key:Q1_R2", "inferred") in kinds  # menghasilkan CO2 vs the key's mengonsumsi CO2
    assert ("ag:menghasilkan", "ag:mengonsumsi", "ontology") in kinds
    reasoning = g["details"]["ans:Q1_A08_t4"]["sections"][1]["items"][0]
    assert "Aturan 1" in reasoning and "incompatibleWith" in reasoning
    assert {e["from"] for e in g["edges"]} | {e["to"] for e in g["edges"]} <= {n["id"] for n in g["nodes"]}
```

In `tests/test_app.py`, replace `test_grade_saf_contradiction` with:

```python
def test_grade_contradiction(at):
    grade(at, "Q1", "Q1_A08")
    assert next(m.value for m in at.metric if m.label == "Skor sistem") == "50.0"
    assert any("ag:contradicts" in c.value for c in at.code)
```

- [ ] **Step 2: Delete the SAF files**

```bash
git rm -r -q data/external/saf data/questions/SAF_* scripts/import_saf.py tests/test_saf.py
git rm -q docs/gold_SAF_*_review.md
```

- [ ] **Step 3: Remove SAF from `io.py`**

Delete the `SAF_DIR = ...` line (keep `TOTAL`, and reword its comment to `# criterion name for a holistic score (one score per answer, no criteria)`). Replace `load_answers`, `load_human_scores` and `annotation_path` with:

```python
def load_answers(include_synthetic=False):
    """answer_id, question_id, text, split, source, synthetic. Real lecturer data always; synthetic on request.

    Synthetic rows are invented (Agent Rule 4).
    """
    sources = [(ROOT / "data" / "answers" / "answers.csv", "real")]
    if include_synthetic:
        sources.append((ROOT / "data" / "synthetic" / "answers.csv", "synthetic"))
    frames = [pd.read_csv(path, dtype=str).assign(source=src) for path, src in sources if path.exists()]
    if not frames:
        return pd.DataFrame(columns=["answer_id", "question_id", "text", "split", "source", "synthetic"])
    df = pd.concat(frames, ignore_index=True)
    df["synthetic"] = df.source == "synthetic"
    dupes = df["answer_id"][df["answer_id"].duplicated()]
    if len(dupes):
        raise ValueError(f"answer_id must be globally unique; duplicates: {sorted(set(dupes))}")
    return df


def load_human_scores(include_synthetic=False):
    paths = [ROOT / "data" / "human" / "scores.csv"]
    if include_synthetic:
        paths.append(ROOT / "data" / "synthetic" / "scores.csv")
    return pd.concat([load_scores(p) for p in paths], ignore_index=True)
```

```python
def annotation_path(answer_id):
    for base in (ROOT / "data" / "annotations", ROOT / "data" / "synthetic" / "annotations"):
        if (base / f"{answer_id}.yaml").exists():
            return base / f"{answer_id}.yaml"
    return None
```

- [ ] **Step 4: Remove SAF from `pipeline.py`, `cli.py`, `evaluate.py`**

`pipeline.run_split`: change the signature to `def run_split(question, mode, split, include_synthetic=False, use_llm_feedback=True, answer_ids=None, run_id=None):`, change the first line to `answers = io.load_answers(include_synthetic)`, delete the two `annotated_only` lines, and delete `"include_saf": include_saf,` from the `run.json` dict.

`cli.py`:
- `cmd_extract`: `answers = io.load_answers(args.synthetic)`.
- `cmd_run`: `run_dir = pipeline.run_split(args.question, args.mode, args.split, args.synthetic, use_llm_feedback=not args.template_feedback)`.
- In `main`, delete both `s.add_argument("--saf", ...)` lines and the `--annotated-only` line.

`evaluate.py`:
- In `human_totals`, change the comment `# holistic score (SAF): no per-criterion breakdown` to `# holistic score: no per-criterion breakdown`.
- In `evaluate`: replace `synthetic, saf = run["include_synthetic"], run.get("include_saf", False)` with `synthetic = run["include_synthetic"]`; replace `if not run["params_frozen"] and not (synthetic or saf):` with `if not run["params_frozen"] and not synthetic:`; replace `io.load_human_scores(synthetic, saf)` with `io.load_human_scores(synthetic)` and `io.load_answers(synthetic, saf)` with `io.load_answers(synthetic)`.
- In `figures`, change `# holistic human scores only (SAF)` to `# holistic human scores only`.
- In `render`, delete the `if run.get("include_saf"):` block (3 lines) and change the not-frozen note to `"> Parameters were not frozen when this run was made (allowed only for synthetic demos)."`.

- [ ] **Step 5: Remove SAF from the app and comments**

`app/streamlit_app.py`:

```python
@st.cache_data
def answers_table():
    df = io.load_answers(include_synthetic=True)
    human = io.load_human_scores(include_synthetic=True)
    totals = {}
    for qid in df.question_id.unique():
        ctx = context(qid)
        sub = human[human.answer_id.isin(df[df.question_id == qid].answer_id)]
        if len(sub):
            totals.update(human_totals(sub, {qid: criterion_weights(ctx.refs)},
                                       dict.fromkeys(sub.answer_id.unique(), qid)).to_dict())
    df["human"] = df.answer_id.map(totals)
    df["annotated"] = df.answer_id.map(lambda a: io.annotation_path(a) is not None)
    return df


def question_label(qid):
    lang = {"id": "ID", "en": "EN"}[context(qid).rubric.get("language", "id")]
    return f"{qid} · {lang}"
```

- In `page_ontology`: `lang = st.radio("Bahasa", ["Semua", "Indonesia", "Inggris"], horizontal=True)` (the `lang.startswith("Indo")` test stays).
- In `page_question`: delete the two lines `if qid.startswith("SAF_"):` / `st.caption("Sumber: SAF ...")`.
- In `page_grade`: `c[0].metric("Nilai manusia" + (" (sintetis)" if a.synthetic else ""), f"{a.human:.1f}")`.

Comments: `src/autograde/normalize.py:12` → `# English`; `config/predicates.yaml:3` → `# lang: id = Indonesian questions, en = English questions, any = offered for every language.`; `config/predicates.yaml:23` → `  # --- English ---`; `ontology/build_ontology.py:16` → `# Indonesian (Q1; validate with the lecturer) and English relations (kept for English questions).`

- [ ] **Step 6: Record the decision and update the README**

Append to `docs/DECISIONS.md`:

```markdown
## 2026-10-24 — SAF dataset dropped

- The SAF subset (data, AI-drafted keys and annotations, import script, tests) is removed; a better dataset will replace it. The only bundled data is Q1 with its synthetic answers.
- Kept because they are generic: holistic `_total` human scores, `language: en` rubrics, English extraction prompts, `lang: en` predicates and the English ontology relations.
- The two open questions about SAF (pronoun subjects, SAF in the article) no longer apply.
```

In the same file, delete the two "Open — needs a human decision" bullets that start with `**Pronoun subjects.**` and `**SAF in the article.**`.

In `README.md`, delete the "SAF subset ..." paragraph and its code block (the lines from `SAF subset (real English answers` through the closing fence after `--annotated-only --template-feedback`).

- [ ] **Step 7: Confirm no SAF reference is left in code or tests**

Run: `grep -rn -i "saf\b\|include_saf\|SAF_" src app tests scripts config ontology README.md | grep -v '\.pyc'`
Expected: no output.

- [ ] **Step 8: Run the full suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass. The count is 147 minus the deleted `test_saf.py` tests, plus the 2 moved tests.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Remove the SAF dataset; keep Q1 and the synthetic demo data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: SQLite record store (`db.py`)

**Files:**
- Create: `src/autograde/schema.sql`, `src/autograde/db.py`, `tests/test_db.py`
- Modify: `.gitignore`, `tests/conftest.py`

**Interfaces:**
- Consumes: `io.ROOT`.
- Produces (used by every later task):
  - `db.db_dir() -> Path`, `db.db_path() -> Path`, `db.connect(create=False) -> sqlite3.Connection`, `db.remove()`
  - errors `db.NoDatabaseError`, `db.SchemaVersionError`; constant `db.SCHEMA_VERSION = 1`
  - `db.is_empty() -> bool`
  - `db.add_course(code, name) -> int`, `db.add_assessment(course_id, name) -> int`
  - `db.add_question(qid, assessment_id, prompt, reference_answer, rubric: dict, gold: dict)`, `db.questions() -> list[str]`, `db.question(qid) -> dict` (keys `id, assessment_id, prompt, reference_answer, rubric, gold`; `KeyError` if unknown)
  - `db.add_answers(rows: list[dict])` (keys `answer_id, question_id, text, split, source, annotation`, optional `student_id`), `db.answers(include_synthetic=False) -> DataFrame[answer_id, question_id, text, split, source, synthetic, annotated]`, `db.annotation(answer_id) -> dict | None`
  - `db.add_human_scores(df)`, `db.human_scores(include_synthetic=False) -> DataFrame[answer_id, rater_id, criterion, score_0_100]`
  - `db.create_run(run_id, mode, split, question, params, params_frozen, reasoner, include_synthetic) -> dict`, `db.finish_run(run_id)`, `db.runs(finished_only=True) -> list[dict]`, `db.run(run_id) -> dict | None`, `db.save_evaluation(run_id, md)`. Run dicts have keys `run_id, mode, split, question, params (dict), params_frozen (bool), reasoner, include_synthetic (bool), created, finished, evaluation_md`.
  - `db.save_result(run_id, question_id, answer_id, res)` where `res` has keys `sentences, students, entries, score, feedback, log, trace` as returned by `pipeline.run_answer`; `db.result(run_id, answer_id) -> dict | None` (JSON columns decoded); `db.result_ids(run_id, question_id=None) -> list[str]`; `db.run_scores(run_id) -> DataFrame[answer_id, question_id, split, source, synthetic, score, sparql_score]`; `db.save_corrected(run_id, answer_id, entries, score)`
  - `db.add_overrides(rows)`, `db.overrides(answer_id=None) -> list[dict]`
  - `db.AUDIT_COLUMNS`, `db.add_evidence_audit(df)`, `db.evidence_audit() -> DataFrame`
  - `db.get_meta(key) -> str | None`, `db.set_meta(key, value)`

- [ ] **Step 1: Add the `fresh_db` fixture and ignore `db/`**

Append to `.gitignore`:

```
db/
```

Append to `tests/conftest.py`:

```python
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """An empty, separate database directory for tests that build their own data."""
    monkeypatch.setenv("AUTOGRADE_DB_DIR", str(tmp_path / "db"))
    return tmp_path / "db"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_db.py`:

```python
"""SQLite record store: schema version, every table's round trip, and the resume guard."""
import sqlite3

import pandas as pd
import pytest

from autograde import db
from autograde.models import Feedback, ScoreResult


@pytest.fixture
def demo(fresh_db):
    db.connect(create=True).close()
    course = db.add_course("C1", "Course")
    assessment = db.add_assessment(course, "Midterm")
    db.add_question("Q9", assessment, "Prompt?", "Ref.", {"question_id": "Q9", "criteria": []},
                    {"question_id": "Q9", "triples": []})
    db.add_answers([
        {"answer_id": "Q9_A1", "question_id": "Q9", "text": "Jawaban é", "split": "test", "source": "real",
         "annotation": {"triples": []}},
        {"answer_id": "Q9_S1", "question_id": "Q9", "text": "x", "split": "pilot", "source": "synthetic",
         "annotation": None}])
    return assessment


def fake_res(score=50.0):
    sc = ScoreResult(answer_id="Q9_UI", score=score, sum_weighted_credit=5, sum_penalty=0, sum_weights=10,
                     params={"lambda": 0.0}, sparql_score=score)
    return {"sentences": [("Q9_UI_s1", "x")], "students": [], "entries": [], "score": sc,
            "feedback": Feedback(answer_id="Q9_UI", claims=[], summary="s"), "log": [],
            "trace": {"sigmas": {("t1", "R1"): 0.9}, "aligned": [("t1", "R1")], "contradictions": []}}


def test_missing_database_is_reported(fresh_db):
    with pytest.raises(db.NoDatabaseError, match="db import"):
        db.questions()


def test_schema_version_mismatch(fresh_db):
    db.connect(create=True).close()
    con = sqlite3.connect(db.db_path())
    con.execute("PRAGMA user_version = 99")
    con.close()
    with pytest.raises(db.SchemaVersionError, match="--replace"):
        db.questions()


def test_questions_answers_and_annotations(demo):
    assert db.questions() == ["Q9"] and not db.is_empty()
    assert db.question("Q9")["gold"] == {"question_id": "Q9", "triples": []}
    with pytest.raises(KeyError):
        db.question("nope")
    assert list(db.answers().answer_id) == ["Q9_A1"] and db.answers().text[0] == "Jawaban é"
    both = db.answers(include_synthetic=True)
    assert list(both.columns) == ["answer_id", "question_id", "text", "split", "source", "synthetic", "annotated"]
    assert both.set_index("answer_id").loc["Q9_S1", ["synthetic", "annotated"]].tolist() == [True, False]
    assert db.annotation("Q9_A1") == {"triples": []}
    assert db.annotation("Q9_S1") is None and db.annotation("zzz") is None


def test_human_scores_filter_by_source(demo):
    db.add_human_scores(pd.DataFrame({"answer_id": ["Q9_A1", "Q9_S1"], "rater_id": ["D1", "D1"],
                                      "criterion": ["K1", "K1"], "score_0_100": [80, 40]}))
    assert db.human_scores().score_0_100.tolist() == [80.0]
    assert len(db.human_scores(include_synthetic=True)) == 2


def test_runs_results_and_resume_guard(demo):
    db.create_run("r1", "gold", "all", "Q9", {"lambda": 0.0}, False, "sparql", True)
    db.create_run("r1", "gold", "all", "Q9", {"lambda": 0.0}, False, "sparql", True)  # resume: same selection
    with pytest.raises(ValueError, match="new run id"):
        db.create_run("r1", "llm", "all", "Q9", {}, False, "sparql", True)
    assert db.runs() == [] and db.runs(finished_only=False)[0]["run_id"] == "r1"
    db.save_result("r1", "Q9", "Q9_UI", fake_res())  # a pasted answer has no answer row
    db.finish_run("r1")
    run = db.run("r1")
    assert run["params"] == {"lambda": 0.0} and run["include_synthetic"] is True and run["finished"]
    assert db.run("nope") is None
    row = db.result("r1", "Q9_UI")
    assert row["score"]["score"] == 50.0 and row["question_id"] == "Q9"
    assert row["trace"]["sigmas"] == [["t1", "R1", 0.9]] and row["ledger_corrected"] is None
    assert db.result_ids("r1") == ["Q9_UI"] and db.result_ids("r1", "Q8") == []
    scores = db.run_scores("r1")
    assert scores.loc[0, "score"] == 50.0 and pd.isna(scores.loc[0, "split"])
    db.save_corrected("r1", "Q9_UI", [], fake_res(60.0)["score"])
    assert db.result("r1", "Q9_UI")["score_corrected"]["score"] == 60.0
    db.save_result("r1", "Q9", "Q9_UI", fake_res())  # re-grading clears the correction
    assert db.result("r1", "Q9_UI")["score_corrected"] is None
    db.save_evaluation("r1", "# report")
    assert db.runs()[0]["evaluation_md"] == "# report"


def test_overrides_meta_and_audit(demo):
    row = {"answer_id": "Q9_A1", "reference_id": "R1", "status": "MATCHED", "by": "DS", "date": "2026-10-24"}
    with pytest.raises(ValueError, match="reason"):
        db.add_overrides([row])
    db.add_overrides([{**row, "reason": "ok"}])
    assert db.overrides("Q9_A1") == [{**row, "reason": "ok"}] and db.overrides() == db.overrides("Q9_A1")
    assert db.get_meta("k") is None
    db.set_meta("k", "1")
    db.set_meta("k", "2")
    assert db.get_meta("k") == "2"
    db.add_evidence_audit(pd.DataFrame([{"row_type": "ledger", "run_id": "r1", "claim_index": 1}]))
    audit = db.evidence_audit()
    assert list(audit.columns) == db.AUDIT_COLUMNS
    assert audit.loc[0, "claim_index"] == "1" and audit.loc[0, "status"] == ""
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_db.py -q`
Expected: collection error `ImportError: cannot import name 'db' from 'autograde'`.

- [ ] **Step 4: Write the schema**

Create `src/autograde/schema.sql`:

```sql
-- AutoGrade-RDF records (schema version 1, see db.SCHEMA_VERSION). Pipeline objects are stored as JSON text.
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE course (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE assessment (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES course(id),
                         name TEXT NOT NULL, UNIQUE (course_id, name));
CREATE TABLE question (id TEXT PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessment(id),
                       prompt TEXT NOT NULL, reference_answer TEXT NOT NULL,
                       rubric TEXT NOT NULL, gold TEXT NOT NULL);
CREATE TABLE student (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES course(id),
                      external_id TEXT NOT NULL, name TEXT, UNIQUE (course_id, external_id));
CREATE TABLE answer (id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES question(id),
                     student_id INTEGER REFERENCES student(id), text TEXT NOT NULL,
                     split TEXT NOT NULL CHECK (split IN ('pilot', 'test')),
                     source TEXT NOT NULL CHECK (source IN ('real', 'synthetic')), annotation TEXT);
CREATE TABLE human_score (answer_id TEXT NOT NULL REFERENCES answer(id), rater_id TEXT NOT NULL,
                          criterion TEXT NOT NULL, score_0_100 REAL NOT NULL,
                          PRIMARY KEY (answer_id, rater_id, criterion));
CREATE TABLE run (id TEXT PRIMARY KEY, mode TEXT NOT NULL, split TEXT NOT NULL, question TEXT NOT NULL,
                  params TEXT NOT NULL, params_frozen INTEGER NOT NULL, reasoner TEXT NOT NULL,
                  include_synthetic INTEGER NOT NULL, created TEXT NOT NULL, finished TEXT, evaluation_md TEXT);
-- answer_id has no foreign key: answers pasted into the app have no answer row.
CREATE TABLE result (run_id TEXT NOT NULL REFERENCES run(id), answer_id TEXT NOT NULL,
                     question_id TEXT NOT NULL REFERENCES question(id),
                     score TEXT NOT NULL, sentences TEXT NOT NULL, students TEXT NOT NULL, ledger TEXT NOT NULL,
                     feedback TEXT NOT NULL, trace TEXT NOT NULL, extraction_log TEXT NOT NULL,
                     ledger_corrected TEXT, score_corrected TEXT, PRIMARY KEY (run_id, answer_id));
CREATE TABLE override (id INTEGER PRIMARY KEY, answer_id TEXT NOT NULL REFERENCES answer(id),
                       reference_id TEXT NOT NULL, status TEXT NOT NULL, "by" TEXT NOT NULL,
                       date TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE evidence_audit (row_type TEXT, run_id TEXT, answer_id TEXT, entry_id TEXT, reference_id TEXT,
                             status TEXT, quoted_sentences TEXT, present_in_answer TEXT, evidence_correct TEXT,
                             claim_index TEXT, text TEXT, ledger_entry_ids TEXT, supported TEXT);
```

- [ ] **Step 5: Write `db.py`**

Create `src/autograde/db.py`:

```python
"""SQLite record store: courses, questions, answers, human scores, runs, results, overrides, evidence audit.

Pipeline objects (rubric, gold key, ledger, score, feedback, trace) are stored as JSON text. One connection per
call, so the app and the CLI can both use the database (WAL mode).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from autograde import io

SCHEMA_VERSION = 1
SCHEMA = Path(__file__).with_name("schema.sql")
ANSWER_COLUMNS = ["answer_id", "question_id", "text", "split", "source", "synthetic", "annotated"]
SCORE_COLUMNS = ["answer_id", "rater_id", "criterion", "score_0_100"]
RUN_SCORE_COLUMNS = ["answer_id", "question_id", "split", "source", "synthetic", "score", "sparql_score"]
RESULT_JSON = ("score", "sentences", "students", "ledger", "feedback", "trace", "extraction_log",
               "ledger_corrected", "score_corrected")
OVERRIDE_KEYS = ("answer_id", "reference_id", "status", "by", "date", "reason")
AUDIT_COLUMNS = ["row_type", "run_id", "answer_id", "entry_id", "reference_id", "status", "quoted_sentences",
                 "present_in_answer", "evidence_correct", "claim_index", "text", "ledger_entry_ids", "supported"]


class NoDatabaseError(RuntimeError):
    pass


class SchemaVersionError(RuntimeError):
    pass


def db_dir():
    return Path(os.environ.get("AUTOGRADE_DB_DIR") or io.ROOT / "db")


def db_path():
    return db_dir() / "autograde.sqlite"


def connect(create=False):
    path = db_path()
    new = not path.exists()
    if new and not create:
        raise NoDatabaseError("no database; run `python -m autograde db import`")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    if new:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        con.close()
        raise SchemaVersionError(f"database schema is version {version}, code expects {SCHEMA_VERSION}; "
                                 "run `python -m autograde db import --replace`")
    return con


@contextmanager
def tx(create=False):
    """One connection for one operation: commits on success, rolls back on error, always closes."""
    con = connect(create)
    try:
        with con:
            yield con
    finally:
        con.close()


def remove():
    """Delete the SQLite files only; never the whole directory, which AUTOGRADE_DB_DIR may point anywhere."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path()) + suffix).unlink(missing_ok=True)


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def is_empty():
    with tx() as c:
        return c.execute("SELECT COUNT(*) FROM question").fetchone()[0] == 0


# ---------- courses and questions ----------

def add_course(code, name):
    with tx() as c:
        return c.execute("INSERT INTO course (code, name) VALUES (?, ?)", (code, name)).lastrowid


def add_assessment(course_id, name):
    with tx() as c:
        return c.execute("INSERT INTO assessment (course_id, name) VALUES (?, ?)", (course_id, name)).lastrowid


def add_question(qid, assessment_id, prompt, reference_answer, rubric, gold):
    with tx() as c:
        c.execute("INSERT INTO question (id, assessment_id, prompt, reference_answer, rubric, gold) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (qid, assessment_id, prompt, reference_answer, _dumps(rubric), _dumps(gold)))


def questions():
    with tx() as c:
        return [r[0] for r in c.execute("SELECT id FROM question ORDER BY id")]


def question(qid):
    with tx() as c:
        row = c.execute("SELECT * FROM question WHERE id = ?", (qid,)).fetchone()
    if row is None:
        raise KeyError(f"unknown question {qid!r}")
    return {**dict(row), "rubric": json.loads(row["rubric"]), "gold": json.loads(row["gold"])}


# ---------- answers and human scores ----------

def add_answers(rows):
    with tx() as c:
        c.executemany("INSERT INTO answer (id, question_id, student_id, text, split, source, annotation) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      [(r["answer_id"], r["question_id"], r.get("student_id"), r["text"], r["split"], r["source"],
                        None if r.get("annotation") is None else _dumps(r["annotation"])) for r in rows])


def answers(include_synthetic=False):
    """Real answers always; synthetic ones on request (Agent Rule 4)."""
    sql = "SELECT id, question_id, text, split, source, annotation IS NOT NULL FROM answer"
    sql += "" if include_synthetic else " WHERE source = 'real'"
    with tx() as c:
        rows = [tuple(r) for r in c.execute(sql + " ORDER BY id")]
    df = pd.DataFrame(rows, columns=[c for c in ANSWER_COLUMNS if c != "synthetic"])
    df["annotated"] = df.annotated.astype(bool)
    df.insert(5, "synthetic", df.source == "synthetic")
    return df


def annotation(answer_id):
    with tx() as c:
        row = c.execute("SELECT annotation FROM answer WHERE id = ?", (answer_id,)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def add_human_scores(df):
    with tx() as c:
        c.executemany("INSERT INTO human_score (answer_id, rater_id, criterion, score_0_100) VALUES (?, ?, ?, ?)",
                      [(r.answer_id, r.rater_id, r.criterion, float(r.score_0_100)) for r in df.itertuples()])


def human_scores(include_synthetic=False):
    sql = ("SELECT h.answer_id, h.rater_id, h.criterion, h.score_0_100 FROM human_score h "
           "JOIN answer a ON a.id = h.answer_id" + ("" if include_synthetic else " WHERE a.source = 'real'")
           + " ORDER BY h.answer_id, h.rater_id, h.criterion")
    with tx() as c:
        rows = [tuple(r) for r in c.execute(sql)]
    df = pd.DataFrame(rows, columns=SCORE_COLUMNS)
    df["score_0_100"] = df.score_0_100.astype(float)
    return df


# ---------- runs and results ----------

def _run(row):
    r = dict(row)
    r["run_id"] = r.pop("id")
    r["params"] = json.loads(r["params"])
    r["params_frozen"], r["include_synthetic"] = bool(r["params_frozen"]), bool(r["include_synthetic"])
    return r


def create_run(run_id, mode, split, question, params, params_frozen, reasoner, include_synthetic):
    """Create the run, or check that the existing run with this id has the same selection (resuming it)."""
    with tx() as c:
        c.execute("INSERT OR IGNORE INTO run (id, mode, split, question, params, params_frozen, reasoner, "
                  "include_synthetic, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (run_id, mode, split, question, _dumps(params), int(params_frozen), reasoner,
                   int(include_synthetic), datetime.now().isoformat(timespec="seconds")))
        run_row = _run(c.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone())
    if (run_row["mode"], run_row["split"], run_row["question"]) != (mode, split, question):
        raise ValueError(f"run {run_id} exists for mode={run_row['mode']} split={run_row['split']} "
                         f"question={run_row['question']}; use a new run id")
    return run_row


def finish_run(run_id):
    with tx() as c:
        c.execute("UPDATE run SET finished = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), run_id))


def runs(finished_only=True):
    """Newest first."""
    sql = "SELECT * FROM run" + (" WHERE finished IS NOT NULL" if finished_only else "") + " ORDER BY created DESC, id DESC"
    with tx() as c:
        return [_run(r) for r in c.execute(sql)]


def run(run_id):
    with tx() as c:
        row = c.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else _run(row)


def save_evaluation(run_id, md):
    with tx() as c:
        c.execute("UPDATE run SET evaluation_md = ? WHERE id = ?", (md, run_id))


def save_result(run_id, question_id, answer_id, res):
    """One graded answer. Replacing a row also clears its lecturer correction (the ledger changed)."""
    trace = res["trace"]
    trace_json = {"sigmas": [[t, r, s] for (t, r), s in sorted(trace["sigmas"].items())],
                  "aligned": [list(p) for p in trace["aligned"]],
                  "contradictions": [list(p) for p in trace["contradictions"]]}
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO result (run_id, answer_id, question_id, score, sentences, students, ledger, "
                  "feedback, trace, extraction_log) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (run_id, answer_id, question_id, _dumps(res["score"].model_dump()),
                   _dumps([list(s) for s in res["sentences"]]), _dumps([t.model_dump() for t in res["students"]]),
                   _dumps([e.model_dump() for e in res["entries"]]), _dumps(res["feedback"].model_dump()),
                   _dumps(trace_json), _dumps(res["log"])))


def result(run_id, answer_id):
    with tx() as c:
        row = c.execute("SELECT * FROM result WHERE run_id = ? AND answer_id = ?", (run_id, answer_id)).fetchone()
    if row is None:
        return None
    out = dict(row)
    for k in RESULT_JSON:
        out[k] = None if out[k] is None else json.loads(out[k])
    return out


def result_ids(run_id, question_id=None):
    sql, args = "SELECT answer_id FROM result WHERE run_id = ?", [run_id]
    if question_id:
        sql, args = sql + " AND question_id = ?", args + [question_id]
    with tx() as c:
        return [r[0] for r in c.execute(sql + " ORDER BY answer_id", args)]


def run_scores(run_id):
    """One row per graded answer; split and source are empty for answers pasted into the app."""
    with tx() as c:
        rows = c.execute("SELECT r.answer_id, r.question_id, a.split, a.source, r.score FROM result r "
                         "LEFT JOIN answer a ON a.id = r.answer_id WHERE r.run_id = ? ORDER BY r.answer_id",
                         (run_id,)).fetchall()
    data = []
    for r in rows:
        sc = json.loads(r["score"])
        data.append([r["answer_id"], r["question_id"], r["split"], r["source"], r["source"] == "synthetic",
                     sc["score"], sc["sparql_score"]])
    return pd.DataFrame(data, columns=RUN_SCORE_COLUMNS)


def save_corrected(run_id, answer_id, entries, score):
    with tx() as c:
        c.execute("UPDATE result SET ledger_corrected = ?, score_corrected = ? WHERE run_id = ? AND answer_id = ?",
                  (_dumps([e.model_dump() for e in entries]), _dumps(score.model_dump()), run_id, answer_id))


# ---------- lecturer corrections and audit ----------

def add_overrides(rows):
    for r in rows:
        missing = [k for k in OVERRIDE_KEYS if k not in r]
        if missing:
            raise ValueError(f"override {r}: missing {', '.join(missing)}")
    with tx() as c:
        c.executemany('INSERT INTO override (answer_id, reference_id, status, "by", date, reason) '
                      "VALUES (?, ?, ?, ?, ?, ?)",
                      [(r["answer_id"], r["reference_id"], r["status"], r["by"], str(r["date"]), r["reason"])
                       for r in rows])


def overrides(answer_id=None):
    sql, args = 'SELECT answer_id, reference_id, status, "by", date, reason FROM override', []
    if answer_id:
        sql, args = sql + " WHERE answer_id = ?", [answer_id]
    with tx() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY id", args)]


def add_evidence_audit(df):
    df = df.reindex(columns=AUDIT_COLUMNS).fillna("").astype(str)
    with tx() as c:
        c.executemany(f"INSERT INTO evidence_audit ({', '.join(AUDIT_COLUMNS)}) "
                      f"VALUES ({', '.join('?' * len(AUDIT_COLUMNS))})", df.itertuples(index=False, name=None))


def evidence_audit():
    with tx() as c:
        rows = [tuple(r) for r in c.execute(f"SELECT {', '.join(AUDIT_COLUMNS)} FROM evidence_audit")]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


# ---------- meta ----------

def get_meta(key):
    with tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def set_meta(key, value):
    with tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (key, value))
```

- [ ] **Step 6: Run the tests**

Run: `conda run -n semantic_web pytest tests/test_db.py -q`
Expected: 6 passed. Then `conda run -n semantic_web pytest -q`: everything still passes.

- [ ] **Step 7: Commit**

```bash
git add .gitignore src/autograde/schema.sql src/autograde/db.py tests/test_db.py tests/conftest.py
git commit -m "Add the SQLite record store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Knowledge graph store (`kg.py`)

**Files:**
- Create: `src/autograde/kg.py`, `tests/test_kg.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `db.db_dir()`, `db.get_meta`, `db.set_meta`, `io.bind_namespaces`, `io.ontology_path()`.
- Produces:
  - `kg.ONTOLOGY = "urn:ag:ontology"`, `kg.KINDS = ("answer", "ledger", "ledger_corrected")`, `kg.LOCK_WAIT_SECONDS = 2.0`, `kg.KGBusyError`
  - `kg.kg_path() -> Path`, `kg.gold_graph_name(qid) -> str`, `kg.answer_graph_name(run_id, answer_id, kind) -> str`, `kg.parse_name(name) -> dict`
  - `kg.put_graph(name, rdflib.Graph)` (replaces), `kg.get_graph(*names) -> rdflib.Graph` (union; unknown names add nothing), `kg.has_graph(name) -> bool`
  - `kg.graphs() -> list[dict]` (keys `name, kind, question, run, answer, triples`), `kg.query(sparql) -> DataFrame | str`, `kg.sync_ontology() -> bool`, `kg.remove()`

- [ ] **Step 1: Install and pin pyoxigraph**

```bash
conda run -n semantic_web pip install pyoxigraph==0.5.13
```

In `requirements.txt`, add the line `pyoxigraph==0.5.13` between `pygments==...` and `pyparsing==...`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_kg.py`:

```python
"""Oxigraph store: named-graph round trip, read-only SPARQL, ontology sync, and the process lock."""
import pyoxigraph
import pytest
from rdflib import RDFS, XSD, Graph, Literal
from rdflib.compare import isomorphic

from autograde import db, io, kg
from autograde.io import AG, ANS, KEY


@pytest.fixture
def store(fresh_db):
    db.connect(create=True).close()


def test_put_get_replace_and_list(store):
    name = kg.answer_graph_name("r1", "Q1_A07", "ledger")
    g = Graph()
    g.add((ANS.e1, AG.credit, Literal("0.5", datatype=XSD.decimal)))
    g.add((ANS.e1, RDFS.label, Literal("é \"kutip\"", lang="id")))
    kg.put_graph(name, g)
    assert isomorphic(kg.get_graph(name), g)
    g2 = Graph()
    g2.add((ANS.e2, AG.credit, Literal("0.5", datatype=XSD.decimal)))
    kg.put_graph(name, g2)  # replaces, never appends
    assert len(kg.get_graph(name)) == 1 and len(kg.get_graph(name, "urn:ag:gold:none")) == 1
    assert kg.has_graph(name) and not kg.has_graph("urn:ag:gold:none")
    assert kg.graphs() == [{"name": name, "kind": "ledger", "question": None, "run": "r1", "answer": "Q1_A07",
                            "triples": 1}]
    with pytest.raises(ValueError, match="bogus"):
        kg.answer_graph_name("r", "a", "bogus")


def test_parse_name():
    assert kg.parse_name("urn:ag:ontology")["kind"] == "ontology"
    assert kg.parse_name(kg.gold_graph_name("Q1")) == {"name": "urn:ag:gold:Q1", "kind": "gold", "question": "Q1",
                                                       "run": None, "answer": None}
    assert kg.parse_name(kg.answer_graph_name("20261024-1_gold_all", "Q1_A07", "ledger_corrected"))["kind"] == \
        "ledger_corrected"


def test_query_select_ask_construct_and_refusals(store):
    g = Graph()
    g.add((KEY.A, AG.weight, Literal("x")))
    kg.put_graph("urn:ag:gold:T", g)
    df = kg.query(io.SPARQL_PREFIXES + "SELECT ?g ?o WHERE { GRAPH ?g { key:A ?p ?o } }")
    assert df.to_dict("records") == [{"g": "urn:ag:gold:T", "o": "x"}]
    assert bool(kg.query("ASK { ?s ?p ?o }")["ASK"][0])
    assert "key:A" in kg.query(io.SPARQL_PREFIXES + "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    with pytest.raises(ValueError, match="SERVICE"):
        kg.query("SELECT * WHERE { SERVICE <http://example.org/sparql> { ?s ?p ?o } }")
    with pytest.raises(SyntaxError):
        kg.query("INSERT DATA { <http://a> <http://b> <http://c> }")


def test_sync_ontology_only_on_change(store):
    assert kg.sync_ontology() is True
    assert kg.sync_ontology() is False
    assert len(kg.get_graph(kg.ONTOLOGY)) > 100
    db.set_meta("ontology_sha256", "stale")
    assert kg.sync_ontology() is True


def test_lock_is_reported_after_retry(store, monkeypatch):
    monkeypatch.setattr(kg, "LOCK_WAIT_SECONDS", 0.3)
    holder = pyoxigraph.Store(str(kg.kg_path()))  # another "process" holding the store
    with pytest.raises(kg.KGBusyError, match="in use by another process"):
        kg.put_graph("urn:t", Graph())
    del holder
    kg.put_graph("urn:t", Graph())  # released: works again


def test_calls_do_not_leak_the_store(store):
    g = Graph()
    g.add((KEY.A, AG.weight, Literal("x")))
    kg.put_graph("urn:ag:gold:T", g)
    kg.get_graph("urn:ag:gold:T")
    kg.graphs()
    kg.query("SELECT * WHERE { ?s ?p ?o }")
    kg.query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    pyoxigraph.Store(str(kg.kg_path()))  # raises if any call above kept a reference
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_kg.py -q`
Expected: collection error `ImportError: cannot import name 'kg' from 'autograde'`.

- [ ] **Step 4: Write `kg.py`**

Create `src/autograde/kg.py`:

```python
"""Oxigraph triple store with one named graph per document: the ontology, each question's gold key, and each
graded answer's answer / ledger / corrected-ledger graphs.

RocksDB holds a process lock while any reference to the store (or to a query result) is alive. Every function
here opens the store, finishes its work, and returns plain Python or rdflib objects, so nothing keeps the lock.
"""
import hashlib
import re
import shutil
import time

import pandas as pd
import pyoxigraph as ox
from rdflib import Graph

from autograde import db, io

ONTOLOGY = "urn:ag:ontology"
GOLD_PREFIX = "urn:ag:gold:"
RUN_PREFIX = "urn:ag:run:"
KINDS = ("answer", "ledger", "ledger_corrected")
LOCK_WAIT_SECONDS = 2.0


class KGBusyError(RuntimeError):
    pass


def kg_path():
    return db.db_dir() / "kg"


def gold_graph_name(qid):
    return f"{GOLD_PREFIX}{qid}"


def answer_graph_name(run_id, answer_id, kind):
    if kind not in KINDS:
        raise ValueError(f"unknown graph kind {kind!r}")
    return f"{RUN_PREFIX}{run_id}:{answer_id}:{kind}"


def parse_name(name):
    out = {"name": name, "kind": "other", "question": None, "run": None, "answer": None}
    if name == ONTOLOGY:
        out["kind"] = "ontology"
    elif name.startswith(GOLD_PREFIX):
        out.update(kind="gold", question=name[len(GOLD_PREFIX):])
    elif name.startswith(RUN_PREFIX):
        run_id, answer_id, kind = name[len(RUN_PREFIX):].rsplit(":", 2)
        out.update(kind=kind, run=run_id, answer=answer_id)
    return out


def _open():
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return ox.Store(str(kg_path()))
        except OSError as e:
            if "lock" not in str(e).lower():
                raise
            if time.monotonic() >= deadline:
                raise KGBusyError("the knowledge graph store is in use by another process (app or CLI); "
                                  "close it and retry") from e
            time.sleep(0.1)


def put_graph(name, graph):
    """Replace the named graph's contents with an rdflib graph."""
    data = graph.serialize(format="nt", encoding="utf-8")
    store = _open()
    node = ox.NamedNode(name)
    store.remove_graph(node)
    store.load(data, format=ox.RdfFormat.N_TRIPLES, to_graph=node)
    store.flush()


def get_graph(*names):
    """Union of the named graphs as one rdflib graph; a name that is not in the store adds nothing."""
    store = _open()
    data = b"".join(store.dump(format=ox.RdfFormat.N_TRIPLES, from_graph=ox.NamedNode(n)) for n in names)
    g = io.bind_namespaces(Graph())
    g.parse(data=data.decode("utf-8"), format="nt")
    return g


def has_graph(name):
    return _open().contains_named_graph(ox.NamedNode(name))


def graphs():
    """Every non-empty named graph with its triple count, sorted by name."""
    store = _open()
    rows = [(s["g"].value, int(s["n"].value))
            for s in store.query("SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")]
    return [{**parse_name(g), "triples": n} for g, n in sorted(rows)]


def query(sparql):
    """Read-only SPARQL over the whole dataset (default graph = union of all named graphs).

    SELECT/ASK -> DataFrame of strings, CONSTRUCT/DESCRIBE -> Turtle text. SERVICE is refused, and updates
    fail to parse (Store.query only accepts queries)."""
    if re.search(r"\bSERVICE\b", sparql, re.I):
        raise ValueError("SERVICE (federated queries to remote endpoints) is disabled")
    store = _open()
    try:
        result = store.query(sparql, use_default_graph_as_union=True)
    finally:
        del store  # a parse error's traceback must not keep the store (and its lock) alive
    if isinstance(result, ox.QueryBoolean):
        return pd.DataFrame({"ASK": [bool(result)]})
    if isinstance(result, ox.QueryTriples):
        g = io.bind_namespaces(Graph())
        g.parse(data=result.serialize(format=ox.RdfFormat.N_TRIPLES).decode("utf-8"), format="nt")
        return g.serialize(format="turtle")
    columns = [v.value for v in result.variables]
    rows = [[None if t is None else t.value for t in row] for row in result]
    return pd.DataFrame(rows, columns=columns)


def sync_ontology():
    """Reload urn:ag:ontology when autograde.owl changed (SHA-256 kept in the meta table). True if reloaded."""
    digest = hashlib.sha256(io.ontology_path().read_bytes()).hexdigest()
    if db.get_meta("ontology_sha256") == digest and has_graph(ONTOLOGY):
        return False
    put_graph(ONTOLOGY, Graph().parse(io.ontology_path(), format="xml"))
    db.set_meta("ontology_sha256", digest)
    return True


def remove():
    """Delete the store directory; refuses (KGBusyError) while another process holds it."""
    if kg_path().exists():
        _open()  # the returned store is dropped at once, releasing the lock
        shutil.rmtree(kg_path())
```

- [ ] **Step 5: Run the tests**

Run: `conda run -n semantic_web pytest tests/test_kg.py -q`
Expected: 6 passed. Then `conda run -n semantic_web pytest -q`: everything passes.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/autograde/kg.py tests/test_kg.py
git commit -m "Add the Oxigraph knowledge graph store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Importer, `db` CLI command and the session test database

**Files:**
- Create: `src/autograde/importer.py`, `tests/test_importer.py`, `tests/test_cli.py`
- Modify: `src/autograde/cli.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: Task 2 `db.*`, Task 3 `kg.*`, `gold.validate`, `gold.check_predicates`, `gold.to_graph`, `extract.extract_gold`, `io.load_scores`, `io.ontology_relations`, `io.load_predicates`.
- Produces:
  - `importer.import_files(replace=False, data_dir=None) -> dict` (keys `questions, answers, human_scores, overrides, evidence_audit`), `importer.ImportDataError`
  - CLI: `python -m autograde db init` and `python -m autograde db import [--replace]`. Every other command exits with the database hint when there is no database or no questions.
  - Session-scoped autouse fixture `imported_db` in `tests/conftest.py`. From now on every test runs against a temp DB imported from the repo's `data/`.

`extract.extract_gold` gains its `annotation` parameter in Task 5. Until then the importer validates annotations by calling it with `path=`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_importer.py`:

```python
"""db import: Q1 + synthetic data into both stores; refuses to overwrite; validates before touching anything."""
import shutil

import pytest
from rdflib import Literal

from autograde import db, gold, importer, io, kg

SYNTHETIC = ["Q1_A07", "Q1_A08", "Q1_S01", "Q1_S02", "Q1_S03", "Q1_S04", "Q1_S05"]


def canon(g):
    """Triples with literals compared by value: Oxigraph stores decimals canonically ("2.0" -> "2")."""
    return {(s, p, o.toPython() if isinstance(o, Literal) else o) for s, p, o in g}


def test_import_loads_q1_and_synthetic_data():
    assert db.questions() == ["Q1"]
    q = db.question("Q1")
    assert q["gold"] == io.load_yaml(io.ROOT / "data" / "questions" / "Q1" / "gold.yaml")
    assert "fotosintesis" in q["prompt"].lower()
    answers = db.answers(include_synthetic=True)
    assert sorted(answers.answer_id) == SYNTHETIC
    assert set(answers.source) == {"synthetic"} and answers.annotated.all()
    assert db.answers().empty  # no real answers are bundled
    assert db.annotation("Q1_S04") == {"triples": []}
    expected = io.load_scores(io.ROOT / "data" / "synthetic" / "scores.csv")
    assert len(db.human_scores(include_synthetic=True)) == len(expected)


def test_gold_graph_matches_the_yaml_key():
    q = db.question("Q1")
    relations, _, _ = io.ontology_relations()
    refs = gold.validate(q["gold"], q["rubric"], relations)
    stored = kg.get_graph(kg.gold_graph_name("Q1"))
    assert canon(stored) == canon(gold.to_graph("Q1", refs, q["rubric"], q["gold"]["concepts"]))
    assert len(kg.get_graph(kg.ONTOLOGY)) > 100


def test_import_refuses_a_non_empty_database():
    with pytest.raises(importer.ImportDataError, match="--replace"):
        importer.import_files()


def test_invalid_data_aborts_before_touching_the_database(fresh_db, tmp_path):
    counts = importer.import_files()
    assert counts["questions"] == 1 and counts["answers"] == 7
    data = tmp_path / "data"
    shutil.copytree(io.ROOT / "data" / "questions" / "Q1", data / "questions" / "Q1")
    raw = io.load_yaml(data / "questions" / "Q1" / "gold.yaml")
    raw["triples"][0]["p"] = "memasak"
    io.save_yaml(raw, data / "questions" / "Q1" / "gold.yaml")
    with pytest.raises(gold.GoldError, match="unknown predicate"):
        importer.import_files(replace=True, data_dir=data)
    assert db.questions() == ["Q1"] and len(db.answers(include_synthetic=True)) == 7
    assert kg.has_graph(kg.gold_graph_name("Q1"))


def test_answer_for_unknown_question_is_rejected(fresh_db, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(io.ROOT / "data" / "questions" / "Q1", data / "questions" / "Q1")
    (data / "answers").mkdir()
    (data / "answers" / "answers.csv").write_text("answer_id,question_id,text,split\nQ7_A1,Q7,x,test\n")
    with pytest.raises(importer.ImportDataError, match="unknown question Q7"):
        importer.import_files(data_dir=data)
```

Create `tests/test_cli.py`:

```python
"""CLI entry points that touch the database."""
import pytest

from autograde import cli


def test_cli_without_database_exits_with_hint(fresh_db):
    with pytest.raises(SystemExit, match="db import"):
        cli.main(["run", "--question", "Q1", "--mode", "gold", "--split", "all"])


def test_db_init_creates_an_empty_database(fresh_db, capsys):
    cli.main(["db", "init"])
    assert "empty database" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="db import"):  # still no questions
        cli.main(["evaluate", "--run", "x"])
```

Add the session fixture to `tests/conftest.py`, directly after `pytest_collection_modifyitems`:

```python
@pytest.fixture(scope="session", autouse=True)
def imported_db(tmp_path_factory):
    """Every test runs against real SQLite + Oxigraph stores imported from the repo's data/."""
    from autograde import importer
    mp = pytest.MonkeyPatch()
    mp.setenv("AUTOGRADE_DB_DIR", str(tmp_path_factory.mktemp("db")))
    importer.import_files()
    yield
    mp.undo()
```

and change the `worked` fixture's signature to `def worked(imported_db):`.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_importer.py tests/test_cli.py -q`
Expected: errors on `ModuleNotFoundError: No module named 'autograde.importer'`.

- [ ] **Step 3: Write `importer.py`**

Create `src/autograde/importer.py`:

```python
"""One-time import of the file-based data/ folder into SQLite + Oxigraph. The only module that reads data/.

Everything is read and validated first; the existing stores are only deleted once the new data is known good.
"""
from pathlib import Path

import pandas as pd

from autograde import db, extract, gold, io, kg

DEMO_COURSE = ("DEMO", "Contoh dek (synthetic)")
DEMO_ASSESSMENT = "Impor dari data/"
OVERRIDE_KEYS = set(db.OVERRIDE_KEYS)


class ImportDataError(ValueError):
    pass


def read_questions(data_dir):
    relations, _, _ = io.ontology_relations()
    gold.check_predicates(io.load_predicates(), relations)
    out = {}
    for d in sorted(p for p in (data_dir / "questions").iterdir() if (p / "gold.yaml").exists()):
        gold_raw, rubric = io.load_yaml(d / "gold.yaml"), io.load_yaml(d / "rubric.yaml")
        out[d.name] = {"prompt": (d / "question.md").read_text(encoding="utf-8").strip(),
                       "reference_answer": (d / "reference_answer.md").read_text(encoding="utf-8").strip(),
                       "rubric": rubric, "gold": gold_raw, "refs": gold.validate(gold_raw, rubric, relations)}
    return out


def read_answers(data_dir, question_ids):
    predicates = io.load_predicates()
    rows = []
    for csv, source, ann_dir in ((data_dir / "answers" / "answers.csv", "real", data_dir / "annotations"),
                                 (data_dir / "synthetic" / "answers.csv", "synthetic",
                                  data_dir / "synthetic" / "annotations")):
        if not csv.exists():
            continue
        for a in pd.read_csv(csv, dtype=str).itertuples():
            if a.question_id not in question_ids:
                raise ImportDataError(f"{csv}: {a.answer_id} refers to unknown question {a.question_id}")
            if a.split not in ("pilot", "test"):
                raise ImportDataError(f"{csv}: {a.answer_id} has split {a.split!r} (pilot or test)")
            ann_path = ann_dir / f"{a.answer_id}.yaml"
            annotation = io.load_yaml(ann_path) if ann_path.exists() else None
            if annotation is not None:
                extract.extract_gold(a.answer_id, path=ann_path, predicates=predicates)  # predicate check
            rows.append({"answer_id": a.answer_id, "question_id": a.question_id, "text": a.text, "split": a.split,
                         "source": source, "annotation": annotation})
    ids = [r["answer_id"] for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ImportDataError(f"answer_id must be globally unique; duplicates: {dupes}")
    return rows


def read_scores(data_dir, answer_ids):
    paths = (data_dir / "human" / "scores.csv", data_dir / "synthetic" / "scores.csv")
    scores = pd.concat([io.load_scores(p) for p in paths], ignore_index=True)
    unknown = sorted(set(scores.answer_id) - answer_ids)
    if unknown:
        raise ImportDataError(f"human scores for unknown answers: {unknown}")
    return scores


def read_overrides(data_dir, answer_ids):
    path = data_dir / "human" / "overrides.yaml"
    rows = (io.load_yaml(path) or []) if path.exists() else []
    for r in rows:
        if not OVERRIDE_KEYS <= set(r) or r["answer_id"] not in answer_ids:
            raise ImportDataError(f"{path}: bad override {r}")
    return rows


def read_audit(data_dir):
    path = data_dir / "human" / "evidence_audit.csv"
    return pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=db.AUDIT_COLUMNS)


def import_files(replace=False, data_dir=None):
    data_dir = Path(data_dir or io.ROOT / "data")
    if not replace and db.db_path().exists() and not db.is_empty():
        raise ImportDataError("the database is not empty; use `python -m autograde db import --replace` "
                              "to rebuild it from data/")
    questions = read_questions(data_dir)
    answers = read_answers(data_dir, set(questions))
    ids = {a["answer_id"] for a in answers}
    scores, overrides, audit = read_scores(data_dir, ids), read_overrides(data_dir, ids), read_audit(data_dir)

    kg.remove()
    db.remove()
    db.connect(create=True).close()
    assessment = db.add_assessment(db.add_course(*DEMO_COURSE), DEMO_ASSESSMENT)
    for qid, q in questions.items():
        db.add_question(qid, assessment, q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    db.add_answers(answers)
    db.add_human_scores(scores)
    db.add_overrides(overrides)
    db.add_evidence_audit(audit)
    for qid, q in questions.items():
        kg.put_graph(kg.gold_graph_name(qid), gold.to_graph(qid, q["refs"], q["rubric"], q["gold"].get("concepts")))
    kg.sync_ontology()
    return {"questions": len(questions), "answers": len(answers), "human_scores": len(scores),
            "overrides": len(overrides), "evidence_audit": len(audit)}
```

- [ ] **Step 4: Add the `db` command and the database check to `cli.py`**

Add the command function after `cmd_audit_template`:

```python
def cmd_db(args):
    from autograde import db, importer, kg
    if args.action == "init":
        db.connect(create=True).close()
        kg.sync_ontology()
        print(f"empty database -> {db.db_dir()}")
    else:
        print(f"imported {importer.import_files(replace=args.replace)} -> {db.db_dir()}")
```

In `main`, register it before `args = p.parse_args(argv)`:

```python
    s = sub.add_parser("db", help="create the database, or import data/ into it")
    s.add_argument("action", choices=["init", "import"])
    s.add_argument("--replace", action="store_true", help="rebuild a non-empty database from data/")
    s.set_defaults(func=cmd_db)
```

and replace the last line `args.func(args)` with:

```python
    if args.command != "db":
        from autograde import db
        try:
            if db.is_empty():
                sys.exit("no questions in the database; run `python -m autograde db import`")
        except (db.NoDatabaseError, db.SchemaVersionError) as e:
            sys.exit(str(e))
    args.func(args)
```

- [ ] **Step 5: Run the tests**

Run: `conda run -n semantic_web pytest tests/test_importer.py tests/test_cli.py -q`
Expected: 7 passed. Then `conda run -n semantic_web pytest -q`: everything passes (other modules still read files, which is fine for now).

- [ ] **Step 6: Try it by hand**

Run: `conda run -n semantic_web python -m autograde db import && conda run -n semantic_web python -m autograde db import`
Expected: the first call prints `imported {'questions': 1, 'answers': 7, ...} -> .../db`; the second fails with `ImportDataError: the database is not empty; use ... --replace`.

- [ ] **Step 7: Commit**

```bash
git add src/autograde/importer.py src/autograde/cli.py tests/test_importer.py tests/test_cli.py tests/conftest.py
git commit -m "Add db import and run every test against an imported database

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Read questions, answers, scores and annotations from the database

**Files:**
- Modify: `src/autograde/io.py`, `src/autograde/gold.py`, `src/autograde/extract.py`, `src/autograde/pipeline.py:32-40`, `src/autograde/importer.py`, `app/streamlit_app.py`
- Test: `tests/test_gold.py`, `tests/test_extract.py`, `tests/test_importer.py`

**Interfaces:**
- Consumes: `db.answers`, `db.human_scores`, `db.questions`, `db.question`, `db.annotation`, `kg.put_graph`, `kg.has_graph`, `kg.gold_graph_name`, `kg.sync_ontology`.
- Produces:
  - `io.load_answers(include_synthetic=False)` / `io.load_human_scores(include_synthetic=False)` / `io.question_ids()`, now from `db`. `io.load_answers` also has the `annotated` column. `io.annotation_path` is removed. `io.load_scores(path)` needs a path.
  - `gold.load(qid)` reads `db.question`; `gold.store_graph(qid) -> (graph_name, refs)`; `gold.build(qid) -> (graph_name, refs)` = `store_graph` + review markdown
  - `extract.extract_gold(answer_id, annotation=None, predicates=None)`: the annotation dict comes from `db.annotation` when omitted, and `LookupError` is raised if there is none. The `path` parameter is removed.

- [ ] **Step 1: Write the failing tests**

In `tests/test_gold.py`, add `db, kg` to the `from autograde import ...` line and replace the `q1` fixture:

```python
@pytest.fixture
def q1():
    q = db.question("Q1")
    return q["gold"], q["rubric"]
```

and append:

```python
def test_store_graph_writes_the_named_graph():
    name, refs = gold.store_graph("Q1")
    assert name == "urn:ag:gold:Q1" and kg.has_graph(name)
    assert len(kg.get_graph(name)) == len(gold.to_graph("Q1", refs, db.question("Q1")["rubric"],
                                                          db.question("Q1")["gold"]["concepts"]))
```

In `tests/test_extract.py`, replace `test_gold_mode` with:

```python
def test_gold_mode():
    annotation = {"triples": [{"s": "tumbuhan", "p": "memakai", "o": "cahaya", "sentences": [3]}]}
    [st] = extract.extract_gold("Q1_A07", annotation=annotation, predicates=PREDS)
    assert (st.p, st.sentence_ids, st.negated) == ("menggunakan", ["Q1_A07_s3"], False)


def test_gold_mode_reads_the_database_and_reports_missing():
    assert [t.p for t in extract.extract_gold("Q1_A08")][-1] == "menghasilkan"
    with pytest.raises(LookupError, match="Q1_NONE"):
        extract.extract_gold("Q1_NONE")
```

In `tests/test_importer.py`, append:

```python
def test_io_reads_the_database():
    assert io.question_ids() == ["Q1"]
    assert io.load_answers().empty and len(io.load_answers(include_synthetic=True)) == 7
    assert set(io.load_human_scores(include_synthetic=True).answer_id) <= set(SYNTHETIC)
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_gold.py tests/test_extract.py tests/test_importer.py -q`
Expected: failures on `AttributeError: module 'autograde.gold' has no attribute 'store_graph'` and `TypeError: extract_gold() got an unexpected keyword argument 'annotation'`.

- [ ] **Step 3: Switch `io.py` to the database**

Replace `load_answers`, `load_human_scores`, `question_ids` and `annotation_path` (delete `annotation_path` entirely) with:

```python
def load_answers(include_synthetic=False):
    """answer_id, question_id, text, split, source, synthetic, annotated. Synthetic rows only on request (Rule 4)."""
    from autograde import db
    return db.answers(include_synthetic)


def load_human_scores(include_synthetic=False):
    from autograde import db
    return db.human_scores(include_synthetic)


def question_ids():
    from autograde import db
    return db.questions()
```

Change `load_scores` so it needs a path (only the importer uses it):

```python
def load_scores(path):
    """Per-criterion human scores CSV: answer_id, rater_id, criterion, score_0_100 (used by the importer)."""
    if not Path(path).exists():
        return pd.DataFrame(columns=["answer_id", "rater_id", "criterion", "score_0_100"])
    df = pd.read_csv(path, dtype={"answer_id": str, "rater_id": str, "criterion": str})
    df["score_0_100"] = df["score_0_100"].astype(float)
    return df
```

Keep `question_dir` for now (Task 6 removes it).

- [ ] **Step 4: Switch `gold.py`**

Change the module docstring to `"""Gold key (from the database) -> validated ReferenceTriples -> urn:ag:gold:<qid> (reified ag:ReferenceTriple individuals)."""`, change `from autograde import io` to `from autograde import db, io, kg`, and replace `load` and `build` with:

```python
def load(qid):
    """Validated (gold_raw, rubric, refs) for a question."""
    q = db.question(qid)
    relations, _, _ = io.ontology_relations()
    check_predicates(io.load_predicates(), relations)
    return q["gold"], q["rubric"], validate(q["gold"], q["rubric"], relations)
```

```python
def store_graph(qid):
    """Write the question's gold graph to the knowledge graph store."""
    gold, rubric, refs = load(qid)
    name = kg.gold_graph_name(qid)
    kg.put_graph(name, to_graph(qid, refs, rubric, gold.get("concepts")))
    return name, refs


def build(qid):
    """Gold graph into the store, plus the lecturer's review table in docs/."""
    name, refs = store_graph(qid)
    gold, rubric, _ = load(qid)
    (io.ROOT / "docs").mkdir(exist_ok=True)
    (io.ROOT / "docs" / f"gold_{qid}_review.md").write_text(review_md(qid, gold, rubric, refs), encoding="utf-8")
    return name, refs
```

In `cli.py`, change `cmd_gold`'s print to `print(f"{len(refs)} reference triples -> named graph {path}\nreview table -> docs/gold_{args.question}_review.md")` and the parser help to `"validate the question's gold key and write its named graph + review table"`.

- [ ] **Step 5: Switch `extract.extract_gold`**

Change `from autograde import io, llm` (whatever the current import line is) to also import `db`, then replace `extract_gold`:

```python
def extract_gold(answer_id, annotation=None, predicates=None):
    """Hand-annotated triples {triples: [{s, p, o, negated, sentences: [1, 2]}]}; from the database by default."""
    if annotation is None:
        annotation = db.annotation(answer_id)
    if annotation is None:
        raise LookupError(f"no triple annotation for {answer_id}")
    aliases = alias_map(predicates or io.load_predicates())
    out = []
    for i, raw in enumerate(annotation.get("triples") or [], 1):
        p = aliases.get(raw["p"].lower())
        if p is None or p == "other":
            raise ValueError(f"{answer_id}: triple {i} has unusable predicate {raw['p']!r}")
        out.append(StudentTriple(id=f"{answer_id}_t{i}", answer_id=answer_id, s_text=raw["s"], p=p, o_text=raw["o"],
                                 negated=bool(raw.get("negated", False)),
                                 sentence_ids=[f"{answer_id}_s{n}" for n in raw["sentences"]]))
    return out
```

In `importer.read_answers`, change the validation call to `extract.extract_gold(a.answer_id, annotation=annotation, predicates=predicates)`.

- [ ] **Step 6: Build the gold graph from the store in `pipeline.Context.load`**

In `pipeline.py`, add `kg` to `from autograde import ...` and replace

```python
        if not (io.question_dir(qid) / "gold.ttl").exists():
            gold.build(qid)
```

with

```python
        if not kg.has_graph(kg.gold_graph_name(qid)):
            gold.store_graph(qid)
```

- [ ] **Step 7: Switch the app's question, answer and annotation reads**

In `app/streamlit_app.py`:
- Add `db, kg` to `from autograde import baselines, io, pipeline`.
- In `answers_table`, delete the line `df["annotated"] = df.answer_id.map(lambda a: io.annotation_path(a) is not None)` (the column now comes from the database).
- Replace `read_md` with:

```python
def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
```

- In `page_question`, replace `d = io.question_dir(qid)` with `q = db.question(qid)`, the two `c1.markdown(read_md(d / "question.md"))` / `c2.markdown(read_md(d / "reference_answer.md"))` calls with `c1.markdown(strip_comments(q["prompt"]))` / `c2.markdown(strip_comments(q["reference_answer"]))`, and the last expander with:

```python
    gold_name = kg.gold_graph_name(qid)
    with st.expander(f"Turtle — named graph `{gold_name}`"):
        st.code(kg.get_graph(gold_name).serialize(format="turtle"), language="turtle")
```

- In `page_grade`, replace the annotation block

```python
        annotation = io.annotation_path(answer_id)
        if annotation is not None:
            by = (io.load_yaml(annotation) or {}).get("annotated_by")
            if by:
                st.warning(f"Anotasi triple jawaban ini ditulis oleh **{by}**.")
```

with

```python
        by = (db.annotation(answer_id) or {}).get("annotated_by")
        if by:
            st.warning(f"Anotasi triple jawaban ini ditulis oleh **{by}**.")
```

and `has_annotation = io.annotation_path(answer_id) is not None` with `has_annotation = db.annotation(answer_id) is not None`.
- Directly after `st.set_page_config(...)`, stop with a clear message when there is no usable database, and keep the ontology graph in sync:

```python
try:
    if db.is_empty():
        raise db.NoDatabaseError("no questions in the database; run `python -m autograde db import`")
    kg.sync_ontology()
except (db.NoDatabaseError, db.SchemaVersionError, kg.KGBusyError) as e:
    st.error(str(e))
    st.stop()
```

- [ ] **Step 8: Run the suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add -A src app tests
git commit -m "Read questions, answers, scores and annotations from the database

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Persist graded answers in the database and the knowledge graph

**Files:**
- Modify: `src/autograde/pipeline.py`, `src/autograde/ledger.py`, `src/autograde/cli.py`, `src/autograde/io.py` (remove `question_dir`), `app/explorer.py`, `app/rdfviz.py`, `app/streamlit_app.py`
- Test: `tests/test_pipeline.py`, `tests/test_ledger.py`, `tests/test_explorer.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.create_run`, `db.finish_run`, `db.runs`, `db.result`, `db.result_ids`, `db.run_scores`, `db.save_result`, `db.save_corrected`, `db.add_overrides`, `db.overrides`, `kg.put_graph`, `kg.get_graph`, `kg.answer_graph_name`, `kg.gold_graph_name`.
- Produces:
  - `pipeline.UI_RUN = "ui"`, `pipeline.ui_run() -> str`
  - `pipeline.run_answer(ctx, answer_id, text, mode, run_id, use_llm_feedback=True) -> dict` (keys `sentences, students, entries, score, feedback, log, trace, run_id`)
  - `pipeline.run_split(...) -> run_id` (resumable), `pipeline.completed_runs() -> list[dict]`. `pipeline.runs_dir` is removed.
  - `ledger.recompute_rows(ledger_graph, gold_graph, lam) -> list`, `ledger.recompute_sparql(ledger_graph, gold_graph, lam) -> float`. `ledger.write` is removed.
  - `explorer.load_answer(run_id, answer_id) -> dict`, `explorer.build(ctx, answers, params, human=None, predicates=None)` where `answers` is a list of `load_answer` dicts
  - `rdfviz.merged_graph(names)`, `rdfviz.answer_graph_names(qid, run_id, answer_id) -> [gold, answer, ledger]`, `rdfviz.run_graph_names(run_id) -> list[str]`, `rdfviz.turtle_file_name(name) -> str`
  - CLI `override --run R [--file overrides.yaml]`

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/test_pipeline.py` from `test_run_answer_gold_mode_writes_everything` through `test_completed_runs_skips_files_and_unfinished_runs`, and `test_skos_preset_finds_the_broader_concept`, with the following. Keep the imports, `STUB`, the `ctx` fixture and `test_broader_similarity_must_be_partial`. Change the import line to `from autograde import db, io, kg, ledger, pipeline`.

```python
@pytest.fixture
def fast_context(monkeypatch):
    """Context.load with the SPARQL reasoner and the stub embedding, for whole-split runs."""
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))


def test_run_answer_gold_mode_stores_everything(ctx):
    text = io.load_yaml(io.ROOT / "tests" / "fixtures" / "worked_example.yaml")["text"]
    run_id = pipeline.ui_run()
    res = pipeline.run_answer(ctx, "Q1_A07", text, "gold", run_id, use_llm_feedback=False)
    assert res["score"].score == pytest.approx(70.0) and res["score"].sparql_score == pytest.approx(70.0)
    row = db.result(run_id, "Q1_A07")
    assert row["question_id"] == "Q1" and row["score"]["score"] == pytest.approx(70.0) and len(row["ledger"]) == 5
    assert row["feedback"]["source"] == "template" and row["sentences"][0][0] == "Q1_A07_s1"
    for kind in ("answer", "ledger"):
        assert len(kg.get_graph(kg.answer_graph_name(run_id, "Q1_A07", kind))) > 0


def test_parity_failure_raises_and_stores_nothing(ctx, monkeypatch):
    monkeypatch.setattr(ledger, "recompute_sparql", lambda *a: 12.3)
    db.create_run("parity", "gold", "all", "Q1", ctx.params, False, "sparql", True)
    with pytest.raises(pipeline.ParityError):
        pipeline.run_answer(ctx, "Q1_A07", "Tumbuhan menyerap sinar matahari.", "gold", "parity",
                            use_llm_feedback=False)
    assert db.result("parity", "Q1_A07") is None


def test_completed_runs_lists_only_finished(ctx):
    db.create_run("unfinished", "gold", "all", "Q1", ctx.params, False, "sparql", True)
    assert "unfinished" not in [r["run_id"] for r in pipeline.completed_runs()]


def test_resume_grades_each_answer_once(fast_context, monkeypatch):
    calls, orig = [], pipeline.run_answer
    monkeypatch.setattr(pipeline, "run_answer", lambda *a, **k: calls.append(a[1]) or orig(*a, **k))
    pipeline.run_split("Q1", "gold", "all", include_synthetic=True, use_llm_feedback=False, run_id="resume")
    assert len(calls) == 7
    pipeline.run_split("Q1", "gold", "all", include_synthetic=True, use_llm_feedback=False, run_id="resume")
    assert len(calls) == 7  # nothing graded twice
    assert "resume" in [r["run_id"] for r in pipeline.completed_runs()]
    assert len(db.result_ids("resume")) == 7


def test_skos_preset_finds_the_broader_concept(ctx):
    import rdfviz
    text = io.load_yaml(io.ROOT / "tests" / "fixtures" / "worked_example.yaml")["text"]
    run_id = pipeline.ui_run()
    pipeline.run_answer(ctx, "Q1_A07", text, "gold", run_id, use_llm_feedback=False)
    g = rdfviz.merged_graph(rdfviz.answer_graph_names("Q1", run_id, "Q1_A07"))
    rows = rdfviz.run_query(g, rdfviz.ANSWER_QUERIES["Kredit parsial karena konsep lebih umum"])
    assert rows.to_dict("records") == [{"entry": "ans:L_Q1_A07_R4", "reference": "key:Q1_R4",
                                        "keyConcept": "key:Glukosa", "studentConcept": "key:Makanan"}]
    for name, query in rdfviz.ANSWER_QUERIES.items():
        rdfviz.run_query(g, query)  # every preset still parses and runs against the stored graphs
```

In `tests/test_ledger.py`, replace the `gold_ttl` fixture and the three tests that write files:

```python
@pytest.fixture
def gold_graph(worked):
    return gold.to_graph("Q1", worked["refs"], worked["rubric"])


@pytest.mark.parametrize("students, lam", [("students", 0.0), ("variant", 0.0), ("variant", 0.5)])
def test_sparql_recompute_matches(worked, gold_graph, students, lam):
    entries = ledger_for(worked, worked[students])
    sparql = ledger.recompute_sparql(ledger.to_graph("Q1", entries), gold_graph, lam)
    assert abs(sparql - score("A", entries, {"lambda": lam}).score) < 1e-9


def test_ttl_shape(worked):
    g = ledger.to_graph("Q1", ledger_for(worked, worked["students"]))
    node = ANS.L_Q1_A07_R5
    assert (node, AG.reference, KEY.Q1_R5) in g and (node, AG.status, AG.Cocok) in g
    assert (node, AG.matchedBy, ANS.Q1_A07_t3) in g


def test_override_r3_gives_90(worked, gold_graph):
    entries = ledger_for(worked, worked["students"])
    ov = [{"answer_id": "Q1_A07", "reference_id": "R3", "status": "MATCHED", "reason": "air disebut", "by": "DS",
           "date": "2026-10-21"}]
    fixed = ledger.apply_overrides(entries, ov, worked["params"])
    assert score("A", fixed, worked["params"]).score == pytest.approx(90.0)
    assert ledger.recompute_sparql(ledger.to_graph("Q1", fixed), gold_graph, 0.0) == pytest.approx(90.0)
    assert entries[2].status == "MISSING" and entries[2].override is None  # originals untouched
    assert fixed[2].override == {"by": "DS", "date": "2026-10-21", "reason": "air disebut",
                                 "original_status": "MISSING"}
    with pytest.raises(ValueError, match="no ledger entry"):
        ledger.apply_overrides(entries, [{**ov[0], "reference_id": "R9"}], worked["params"])
```

and remove the now-unused `import json` and `from rdflib import Graph`.

In `tests/test_explorer.py`, replace `graded`:

```python
def graded(qid, answer_id, text):
    ctx = pipeline.Context.load(qid, reasoner="sparql", cosine=STUB)
    run_id = pipeline.ui_run()
    pipeline.run_answer(ctx, answer_id, text, "gold", run_id, use_llm_feedback=False)
    return ctx, explorer.load_answer(run_id, answer_id)
```

Then update its three callers: drop the `tmp_path` argument (`graded("Q1", "Q1_A08", text)` and so on) and the `tmp_path` test parameters, and rename `d` to `a`, so the build calls become `explorer.build(ctx, [a], ctx.params)`.

Append to `tests/test_cli.py`:

```python
def test_override_and_recompute_via_cli(tmp_path, monkeypatch, capsys):
    from autograde import db, io, kg, pipeline
    from test_pipeline import STUB
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    pipeline.run_split("Q1", "gold", "all", include_synthetic=True, use_llm_feedback=False, run_id="cli")
    path = tmp_path / "ov.yaml"
    io.save_yaml([{"answer_id": "Q1_A07", "reference_id": "R3", "status": "MATCHED", "reason": "air disebut",
                   "by": "DS", "date": "2026-10-21"}], path)
    cli.main(["override", "--run", "cli", "--file", str(path)])
    row = db.result("cli", "Q1_A07")
    assert row["score"]["score"] == pytest.approx(70.0) and row["score_corrected"]["score"] == pytest.approx(90.0)
    assert len(kg.get_graph(kg.answer_graph_name("cli", "Q1_A07", "ledger_corrected"))) > 0
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["recompute", "--run", "cli", "--answer", "Q1_A07"])
    assert exit_info.value.code == 0 and "OK" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_pipeline.py tests/test_ledger.py tests/test_explorer.py tests/test_cli.py -q`
Expected: failures such as `AttributeError: module 'autograde.pipeline' has no attribute 'ui_run'` and `TypeError` in `recompute_sparql`.

- [ ] **Step 3: `ledger.py`: graphs in, no files out**

Change the module docstring to `"""One LedgerEntry per reference triple; RDF graph; SPARQL score recompute; lecturer overrides."""`, delete `import csv`, change `from autograde.io import AG, ANS, KEY, PROV, save_json` to `from autograde.io import AG, ANS, KEY, PROV`, delete `write`, and replace `recompute_sparql` with:

```python
def recompute_rows(ledger_graph, gold_graph, lam):
    """The recompute query's rows over a ledger graph and its question's gold graph."""
    return list((ledger_graph + gold_graph).query(RECOMPUTE_QUERY, initBindings={"lambda": _dec(lam)}))


def recompute_sparql(ledger_graph, gold_graph, lam):
    """Score from the RDF graphs alone (as read back from the store), clamped at 0 like Eq. 6."""
    rows = recompute_rows(ledger_graph, gold_graph, lam)
    if len(rows) != 1:
        raise ValueError(f"expected one answer in the ledger graph, got {len(rows)}")
    return max(0.0, float(rows[0].raw.toPython()))
```

In `answer_graph`'s docstring, change `(the deck's jawaban.ttl)` to `(the deck's answer graph)`. In `models.py:7`, change `used in ledger.ttl` to `used in the ledger graph`.

- [ ] **Step 4: `pipeline.py`: results into the stores, resumable runs**

Change the module docstring to `"""Orchestrates one answer, one question, or a whole split; stores results in the database and the knowledge graph."""`, add `db` to `from autograde import ...`, delete `import json` and `import pandas as pd` if they become unused, and replace everything from `def run_answer` to the end of the file with:

```python
UI_RUN = "ui"


def ui_run():
    """The app's run for single answers graded on the Grade page: never finished, never evaluated."""
    db.create_run(UI_RUN, "ui", "all", "all", io.load_params(), io.frozen_path().exists(),
                  io.load_config()["reasoner"], True)
    return UI_RUN


def run_answer(ctx, answer_id, text, mode, run_id, use_llm_feedback=True):
    sentences = segment.split(answer_id, text)
    students, log = extract_triples(ctx, answer_id, sentences, mode)
    students, entries, sc, trace = grade(ctx, answer_id, students)
    answer_name = kg.answer_graph_name(run_id, answer_id, "answer")
    ledger_name = kg.answer_graph_name(run_id, answer_id, "ledger")
    kg.put_graph(answer_name, ledger.answer_graph(answer_id, students, sentences, ctx.qid, trace))
    kg.put_graph(ledger_name, ledger.to_graph(ctx.qid, entries))
    # the audit reads the graphs back from the store: it checks what was persisted, not what is in memory
    sc.sparql_score = ledger.recompute_sparql(kg.get_graph(ledger_name), kg.get_graph(kg.gold_graph_name(ctx.qid)),
                                              ctx.params["lambda"])
    if abs(sc.score - sc.sparql_score) >= 1e-9:
        raise ParityError(f"{answer_id}: Python score {sc.score} != SPARQL score {sc.sparql_score}")
    fb = feedback.generate(answer_id, entries, ctx.refs, ctx.rubric, sentences, sc.score, use_llm=use_llm_feedback)
    res = {"sentences": sentences, "students": students, "entries": entries, "score": sc, "feedback": fb,
           "log": log, "trace": trace, "run_id": run_id}
    db.save_result(run_id, ctx.qid, answer_id, res)  # last: the row marks the answer as done
    return res


def completed_runs():
    """Finished runs, newest first (dicts from the run table)."""
    return db.runs(finished_only=True)


def run_split(question, mode, split, include_synthetic=False, use_llm_feedback=True, answer_ids=None, run_id=None):
    """Grade a selection of answers. Re-running the same run_id resumes it: graded answers are skipped."""
    answers = io.load_answers(include_synthetic)
    if question != "all":
        answers = answers[answers.question_id == question]
    if split != "all":
        answers = answers[answers.split == split]
    if answer_ids:
        answers = answers[answers.answer_id.isin(answer_ids)]
    if answers.empty:
        raise ValueError("no answers selected (import real answers with `db import`; use --synthetic for demo data)")
    run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}_{mode}_{split}"
    db.create_run(run_id, mode, split, question, io.load_params(), io.frozen_path().exists(),
                  io.load_config()["reasoner"], include_synthetic)
    done, contexts = set(db.result_ids(run_id)), {}
    for a in answers.itertuples():
        if a.answer_id in done:
            print(f"{a.answer_id}: already graded, skipped")
            continue
        ctx = contexts.setdefault(a.question_id, Context.load(a.question_id))
        res = run_answer(ctx, a.answer_id, a.text, mode, run_id, use_llm_feedback)
        print(f"{a.answer_id}: {res['score'].score:.1f}")
    db.finish_run(run_id)
    return run_id
```

- [ ] **Step 5: `cli.py`: run, recompute and override on the stores**

Replace `cmd_run`, `cmd_recompute`, `_question_of` (delete it) and `cmd_override` with:

```python
def cmd_run(args):
    from autograde import pipeline
    run_id = pipeline.run_split(args.question, args.mode, args.split, args.synthetic,
                                use_llm_feedback=not args.template_feedback, run_id=args.run_id)
    print(f"run -> {run_id}")


def _run_or_exit(run_id):
    from autograde import db
    run = db.run(run_id)
    if run is None:
        sys.exit(f"no run {run_id}")
    return run


def cmd_recompute(args):
    from autograde import db, kg, ledger
    run, res = _run_or_exit(args.run), db.result(args.run, args.answer)
    if res is None:
        sys.exit(f"{args.answer} is not in run {args.run}")
    sparql = ledger.recompute_sparql(kg.get_graph(kg.answer_graph_name(args.run, args.answer, "ledger")),
                                     kg.get_graph(kg.gold_graph_name(res["question_id"])), run["params"]["lambda"])
    stored = res["score"]["score"]
    ok = abs(sparql - stored) < 1e-9
    print(f"{args.answer}: SPARQL {sparql:.4f} | stored {stored:.4f} | {'OK' if ok else 'MISMATCH'}")
    sys.exit(0 if ok else 1)


def cmd_override(args):
    from autograde import db, kg, ledger, pipeline
    from autograde.models import LedgerEntry
    from autograde.score import score
    params = _run_or_exit(args.run)["params"]
    if args.file:
        db.add_overrides(io.load_yaml(args.file) or [])
    overrides = db.overrides()
    for answer_id in sorted({o["answer_id"] for o in overrides}):
        res = db.result(args.run, answer_id)
        if res is None:
            print(f"{answer_id}: not in run {args.run}, skipped")
            continue
        qid = res["question_id"]
        fixed = ledger.apply_overrides([LedgerEntry(**e) for e in res["ledger"]],
                                       [o for o in overrides if o["answer_id"] == answer_id], params)
        name = kg.answer_graph_name(args.run, answer_id, "ledger_corrected")
        kg.put_graph(name, ledger.to_graph(qid, fixed))
        sc = score(answer_id, fixed, params)
        sc.sparql_score = ledger.recompute_sparql(kg.get_graph(name), kg.get_graph(kg.gold_graph_name(qid)),
                                                  params["lambda"])
        if abs(sc.score - sc.sparql_score) >= 1e-9:
            raise pipeline.ParityError(f"{answer_id}: corrected score parity failed")
        db.save_corrected(args.run, answer_id, fixed, sc)
        print(f"{answer_id}: {res['score']['score']:.1f} -> {sc.score:.1f} (corrected)")
```

In `main`: on the `run` parser add `s.add_argument("--run-id", help="resume (or name) a run; graded answers are skipped")`; replace the `override` parser block with:

```python
    s = sub.add_parser("override", help="apply the lecturer's overrides (optionally adding them from a YAML file) to a run")
    s.add_argument("--run", required=True)
    s.add_argument("--file", help="YAML list of overrides to add first (answer_id, reference_id, status, by, date, reason)")
    s.set_defaults(func=cmd_override)
```

- [ ] **Step 6: `explorer.py`: answers from the database**

Change the module docstring's second sentence to: `Node ids are the RDF names (ag: schema, key: lecturer's data, ans: student data) and edge labels are the RDF/OWL property names, so the picture is the same graph stored in the knowledge graph (gold, answer and ledger named graphs plus the ontology).` Add `db` to `from autograde import gold, io`. Replace `load_answer`:

```python
def load_answer(run_id, answer_id):
    """One graded answer as stored by pipeline.run_answer."""
    r = db.result(run_id, answer_id)
    if r is None:
        raise LookupError(f"{answer_id} is not in run {run_id}")
    return {"answer_id": answer_id,
            "students": [StudentTriple(**t) for t in r["students"]],
            "entries": [LedgerEntry(**e) for e in r["ledger"]],
            "sentences": [tuple(s) for s in r["sentences"]],
            "score": r["score"],
            "sigmas": {(t, ref): s for t, ref, s in r["trace"]["sigmas"]},
            "aligned": {tuple(x) for x in r["trace"]["aligned"]},
            "contradictions": {tuple(x) for x in r["trace"]["contradictions"]}}
```

In `build`, change the signature to `def build(ctx, answers, params, human=None, predicates=None):`, delete the line `answers = [load_answer(d) for d in answer_dirs]`, change the comment `# --- the lecturer's key (gold.ttl) ---` to `# --- the lecturer's key (gold graph) ---`, and change `# --- the graded answers (answer.ttl + ledger.ttl) ---` to `# --- the graded answers (answer + ledger graphs) ---`.

- [ ] **Step 7: `rdfviz.py`: graph names instead of paths**

Add `from autograde import db, kg` next to `from autograde import io`, and replace `merged_graph`, `answer_graph_paths` and `run_graph_paths` with:

```python
def merged_graph(names):
    """Ontology plus named graphs from the store, as one rdflib graph for the SPARQL console."""
    g = io.bind_namespaces(Graph())
    for triple in io.ontology_graph():
        g.add(triple)
    for triple in kg.get_graph(*names):
        g.add(triple)
    return g


def answer_graph_names(qid, run_id, answer_id):
    return [kg.gold_graph_name(qid), kg.answer_graph_name(run_id, answer_id, "answer"),
            kg.answer_graph_name(run_id, answer_id, "ledger")]


def run_graph_names(run_id):
    scores = db.run_scores(run_id)
    names = [kg.gold_graph_name(q) for q in sorted(set(scores.question_id))]
    for a in scores.answer_id:
        names += [kg.answer_graph_name(run_id, a, "answer"), kg.answer_graph_name(run_id, a, "ledger")]
    return names


def turtle_file_name(name):
    """urn:ag:gold:Q1 -> gold_Q1.ttl"""
    return name.split(":", 2)[2].replace(":", "_") + ".ttl"
```

- [ ] **Step 8: Remove `io.question_dir`**

Delete `question_dir` from `io.py`, then run `grep -rn "question_dir\|runs_dir\|out_dir" src app` and fix any remaining hit in the next step.

- [ ] **Step 9: The app on the stores**

In `app/streamlit_app.py`:

- `page_grade`: change the grading call to `res = pipeline.run_answer(ctx, answer_id, text, mode, pipeline.ui_run(), use_llm_fb)`.
- `show_result`, tab 1: `components.html(explorer.html(explorer.build(ctx, [explorer.load_answer(res["run_id"], answer_id)], ctx.params, human), height=600), height=700, scrolling=False)`.
- `show_result`, tabs 4 and 5: replace both bodies with:

```python
    names = rdfviz.answer_graph_names(qid, res["run_id"], answer_id)
    with tabs[4]:
        captions = ["Graf acuan (kunci dosen)", "Triple jawaban + provenance PROV-O + masukan/keluaran penalaran",
                    "Ledger: satu ag:LedgerEntry per triple acuan"]
        for name, caption in zip(names, captions):
            ttl = kg.get_graph(name).serialize(format="turtle")
            with st.expander(f"{caption} — `{name}`", expanded=name.endswith(":ledger")):
                st.code(ttl, language="turtle")
                st.download_button("Unduh Turtle", ttl, file_name=rdfviz.turtle_file_name(name), key=f"dl_{name}")
    with tabs[5]:
        g = rdfviz.merged_graph(names)
        st.caption(f"Graf gabungan: ontologi + {', '.join(f'`{n}`' for n in names)} ({len(g)} triple). Hanya baca.")
        sparql_console(g, rdfviz.ANSWER_QUERIES, "ans")
```

- `show_ledger`: replace the two `ov_path` lines with `overrides = db.overrides(answer_id)`.
- `page_sparql`: replace from `runs = pipeline.completed_runs()` to the end of the function with:

```python
    runs = pipeline.completed_runs()
    options = (["Jawaban terakhir yang dinilai"] if graded else []) + [f"Run: {r['run_id']}" for r in runs]
    if not options:
        st.info("Nilai sebuah jawaban dulu, atau buat run: `python -m autograde run …`.")
        return
    choice = st.selectbox("Graf", options)
    if choice.startswith("Jawaban"):
        g = rdfviz.merged_graph(rdfviz.answer_graph_names(graded["qid"], graded["res"]["run_id"], graded["answer_id"]))
        presets = rdfviz.ANSWER_QUERIES
    else:
        g = rdfviz.merged_graph(rdfviz.run_graph_names(choice.removeprefix("Run: ")))
        presets = {**rdfviz.RUN_QUERIES, **rdfviz.ANSWER_QUERIES}
    st.caption(f"{len(g)} triple RDF dimuat dari triple store.")
    sparql_console(g, presets, "global")
```

- `page_explorer`: replace from `sources = {}` through the `components.html(...)` call with:

```python
    sources = {}
    for run in pipeline.completed_runs():
        ids = db.result_ids(run["run_id"], qid)
        if ids:
            sources[f"Run {run['run_id']} · {len(ids)} jawaban"] = (run["run_id"], ids, run["params"])
    ui_ids = db.result_ids(pipeline.UI_RUN, qid)
    if ui_ids:
        sources[f"Dinilai di aplikasi · {len(ui_ids)} jawaban"] = (pipeline.UI_RUN, ui_ids, ctx.params)
    if not sources:
        st.info("Belum ada jawaban yang dinilai untuk soal ini. Nilai jawaban di halaman *Nilai Jawaban*, atau buat run "
                "dengan `python -m autograde run …`. Graf kunci tetap ditampilkan di bawah.")
        run_id, ids, params = None, [], ctx.params
    else:
        run_id, ids, params = sources[st.selectbox("Sumber jawaban", list(sources))]
    chosen = st.multiselect("Jawaban yang ditampilkan", ids, default=ids[:12]) if ids else []
    human = answers_table().set_index("answer_id").human.dropna().to_dict()
    graph = explorer.build(ctx, [explorer.load_answer(run_id, a) for a in chosen], params, human)
    st.caption(f"{len(graph['nodes'])} node · {len(graph['edges'])} relasi")
    components.html(explorer.html(graph, height=640), height=740, scrolling=False)
```

- `page_evaluation` still reads run folders. Replace it now with a stub, which Task 7 completes:

```python
def page_evaluation():
    st.info("Belum ada hasil evaluasi. Jalankan `python -m autograde evaluate --run <run_id>`.")
```

- [ ] **Step 10: `evaluate.py` and `calibrate.py` interim check**

`evaluate.py` still uses `pipeline.runs_dir`, which no longer exists. Task 7 rewrites it, but the suite must stay green in between, so mark the three file-based tests in `tests/test_evaluate.py` (`test_evaluate_synthetic_and_deterministic`, `test_unfrozen_real_run_refused`, `test_audit_template_and_metrics`) with `@pytest.mark.skip(reason="moved to the database in Task 7")`. Task 7 removes the marks. `calibrate.py` needs no change: it only uses `io.load_answers` / `io.load_human_scores`.

- [ ] **Step 11: Run the suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass except the 3 skipped evaluate tests.

- [ ] **Step 12: Try it by hand**

```bash
conda run -n semantic_web python -m autograde db import --replace
conda run -n semantic_web python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback --run-id demo
conda run -n semantic_web python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback --run-id demo
conda run -n semantic_web python -m autograde recompute --run demo --answer Q1_A08
```

Expected: the first run prints one score per answer (7 lines; Q1_A08 is 50.0 because its contradiction is found by rules, not embeddings). The second prints `Q1_...: already graded, skipped` 7 times. `recompute` prints `Q1_A08: SPARQL 50.0000 | stored 50.0000 | OK`.

- [ ] **Step 13: Commit**

```bash
git add -A src app tests
git commit -m "Store graded answers in the database and the knowledge graph; resumable runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Evaluation and evidence audit on the database

**Files:**
- Modify: `src/autograde/evaluate.py`, `src/autograde/cli.py`, `app/streamlit_app.py` (`page_evaluation`)
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `db.run`, `db.run_scores`, `db.result`, `db.evidence_audit`, `db.add_evidence_audit`, `db.save_evaluation`, `db.create_run`.
- Produces:
  - `evaluate.report_dir(run_id) -> Path` (`outputs/reports/<run_id>`), `evaluate.load_ledger(run_id, answer_id, corrected=False)`
  - `evaluate.evaluate(run_id, gold_run_id=None, b2_backend=None) -> str` (the markdown report, also saved with `db.save_evaluation`)
  - `evaluate.audit_template(run_id) -> Path`
  - CLI `audit-import --file <csv>`

- [ ] **Step 1: Rewrite the three evaluate tests for the database**

In `tests/test_evaluate.py`, change the import line to `from autograde import db, evaluate, io, pipeline`, remove the three `skip` marks, and replace the `synthetic_run` fixture and those three tests with:

```python
@pytest.fixture
def synthetic_run(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "report_dir", lambda run_id: tmp_path / run_id)
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    return pipeline.run_split("Q1", "gold", "all", include_synthetic=True, use_llm_feedback=False, run_id="eval_t")


def test_evaluate_synthetic_and_deterministic(synthetic_run):
    fail_b2 = lambda *a: (_ for _ in ()).throw(evaluate.llm.LLMUnavailable("no key"))
    report = evaluate.evaluate(synthetic_run, b2_backend=fail_b2)
    metrics_path = evaluate.report_dir(synthetic_run) / "metrics.csv"
    first = metrics_path.read_bytes()
    evaluate.evaluate(synthetic_run, b2_backend=fail_b2)
    assert metrics_path.read_bytes() == first
    assert "SYNTHETIC DATA" in report and "B2 LLM-only not computed" in report
    assert db.run(synthetic_run)["evaluation_md"] == report
    metrics = pd.read_csv(metrics_path)
    assert set(metrics.system) == {"System (gold mode)", "System (gold mode), λ = 0.5", "B1 keyword"}


def test_unfrozen_real_run_refused():
    db.create_run("unfrozen", "gold", "test", "Q1", io.load_params(), False, "sparql", False)
    with pytest.raises(evaluate.NotFrozenError):
        evaluate.evaluate("unfrozen")


def test_audit_template_and_metrics(synthetic_run):
    template = pd.read_csv(evaluate.audit_template(synthetic_run), dtype=str).fillna("")
    led = template.row_type == "ledger"
    template.loc[led, "present_in_answer"] = "yes"
    template.loc[led & template.status.isin(["MATCHED", "PARTIAL"]), "evidence_correct"] = "yes"
    template.loc[template.row_type == "claim", "supported"] = "no"
    db.add_evidence_audit(template)
    m = evaluate.audit_metrics(synthetic_run)
    hits = (led & template.status.isin(["MATCHED", "PARTIAL"])).sum()
    assert m["EP"] == (1.0, hits)
    assert m["ER"][0] == pytest.approx(hits / led.sum())
    assert m["FF"][0] == 0.0
```

`test_audit_template_and_metrics` adds audit rows to the shared session database, but `audit_metrics` filters by `run_id`, so other runs are not affected.

- [ ] **Step 2: Run them to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_evaluate.py -q`
Expected: failures on `AttributeError: module 'autograde.evaluate' has no attribute 'report_dir'`.

- [ ] **Step 3: Rewrite the run access in `evaluate.py`**

Change `from autograde import baselines, gold, io, llm` to `from autograde import baselines, db, gold, io, llm`. Replace `load_ledger` with:

```python
def report_dir(run_id):
    """Metrics CSVs and figures; the report text itself is stored with the run in the database."""
    return io.ROOT / "outputs" / "reports" / run_id


def load_ledger(run_id, answer_id, corrected=False):
    r = db.result(run_id, answer_id)
    return [LedgerEntry(**e) for e in (r["ledger_corrected"] if corrected else r["ledger"])]
```

In `audit_metrics`, replace the first four lines (from `path = ...` through `df = df[df.run_id == run_id]`) with:

```python
    df = db.evidence_audit()
    df = df[df.run_id == run_id]
    if df.empty:
        return {}
```

In `evaluate`, replace the opening lines through `h = human[runs.answer_id].to_numpy()` and the `texts`/`lam05`/`gold_run_id` lines as follows (the rest of the computation is unchanged):

```python
def evaluate(run_id, gold_run_id=None, b2_backend=None):
    run = db.run(run_id)
    if run is None:
        raise LookupError(f"no run {run_id}")
    synthetic = run["include_synthetic"]
    if not run["params_frozen"] and not synthetic:
        raise NotFrozenError("this run used unfrozen parameters; run `calibrate` and re-run the test split")
    if run["split"] not in ("test", "all"):
        raise ValueError("evaluate needs a run that covers the test split")
    runs = db.run_scores(run_id)
    runs = runs[runs.split == "test"].sort_values("answer_id").reset_index(drop=True)
    question_of = dict(zip(runs.answer_id, runs.question_id))
    ctx = {q: gold.load(q) for q in sorted(set(runs.question_id))}
    weights = {q: gold.criterion_weights(refs) for q, (_, _, refs) in ctx.items()}
    scores = io.load_human_scores(synthetic)
    scores = scores[scores.answer_id.isin(runs.answer_id)]
    human = human_totals(scores, weights, question_of)
    runs = runs[runs.answer_id.isin(human.index)]
    h = human[runs.answer_id].to_numpy()

    texts = io.load_answers(synthetic).set_index("answer_id").text
    systems = {f"System ({run['mode']} mode)": runs.score.to_numpy()}
    lam05 = [score(a, load_ledger(run_id, a), {"lambda": 0.5}).score for a in runs.answer_id]
    systems[f"System ({run['mode']} mode), λ = 0.5"] = np.array(lam05)
    if gold_run_id:
        g = db.run_scores(gold_run_id).set_index("answer_id")
        systems["System (gold mode)"] = g.loc[runs.answer_id, "score"].to_numpy()
```

Further down: change `criterion_scores(load_ledger(run_dir, a))` to `criterion_scores(load_ledger(run_id, a))`, and replace the output block (from `metrics.round(6).to_csv(run_dir / "metrics.csv", ...)` to the `return`) with:

```python
    out = report_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    metrics.round(6).to_csv(out / "metrics.csv", index=False)
    per_question.round(6).to_csv(out / "metrics_per_question.csv", index=False)
    per_criterion.round(6).to_csv(out / "per_criterion_mae.csv")
    figures(out, runs.score.to_numpy(), h, per_criterion)
    report = render(run, metrics, per_criterion, icc, recon, audit, b2_note, len(runs))
    db.save_evaluation(run_id, report)
    return report
```

In `render`: change `"", "Per-question rows: \`metrics_per_question.csv\`.", ""` to reference `outputs/reports/{run['run_id']}/metrics_per_question.csv`. Change the pending audit text to `f"- {label} ({key}): pending — no evidence audit imported for this run (\`audit-template\`, then \`audit-import\`)"`. Change the figures line to `f"Figures: \`outputs/reports/{run['run_id']}/scatter.png\`, \`per_criterion.png\`."`.

Replace `audit_template`:

```python
def audit_template(run_id):
    rows = []
    for a in db.run_scores(run_id).answer_id:
        r = db.result(run_id, a)
        sentences = {sid: text for sid, text in r["sentences"]}
        for e in (LedgerEntry(**x) for x in r["ledger"]):
            rows.append({"row_type": "ledger", "run_id": run_id, "answer_id": a, "entry_id": e.entry_id,
                         "reference_id": e.reference_id, "status": e.status,
                         "quoted_sentences": " ".join(sentences.get(s, "") for s in e.sentence_ids),
                         "present_in_answer": "", "evidence_correct": ""})
        for i, c in enumerate(r["feedback"]["claims"], 1):
            rows.append({"row_type": "claim", "run_id": run_id, "answer_id": a, "claim_index": i, "text": c["text"],
                         "ledger_entry_ids": " ".join(c["ledger_entry_ids"]), "supported": ""})
    out = report_dir(run_id) / "evidence_audit_template.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=db.AUDIT_COLUMNS).to_csv(out, index=False)
    return out
```

- [ ] **Step 4: CLI**

Replace `cmd_evaluate` and add `cmd_audit_import`:

```python
def cmd_evaluate(args):
    from autograde import evaluate
    print(evaluate.evaluate(args.run, gold_run_id=args.gold_run))
    print(f"metrics and figures -> {evaluate.report_dir(args.run)}")


def cmd_audit_import(args):
    import pandas as pd
    from autograde import db
    df = pd.read_csv(args.file, dtype=str).fillna("")
    db.add_evidence_audit(df)
    print(f"{len(df)} evidence audit rows imported")
```

In `main`, change the `audit-template` help to `"blank evidence audit CSV for the lecturer (outputs/reports/<run>/)"` and register:

```python
    s = sub.add_parser("audit-import", help="import the lecturer's filled evidence audit CSV")
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_audit_import)
```

- [ ] **Step 5: The evaluation page**

In `app/streamlit_app.py`, add `evaluate` to the `from autograde import ...` line and replace the stub `page_evaluation`:

```python
def page_evaluation():
    runs = [r for r in pipeline.completed_runs() if r["evaluation_md"]]
    if not runs:
        st.info("Belum ada hasil evaluasi. Jalankan `python -m autograde evaluate --run <run_id>`.")
        return
    run = st.selectbox("Run", runs, format_func=lambda r: r["run_id"])
    st.markdown(run["evaluation_md"])
    out = evaluate.report_dir(run["run_id"])
    for col, name in zip(st.columns(2), ["scatter.png", "per_criterion.png"]):
        if (out / name).exists():
            col.image(str(out / name))
```

- [ ] **Step 6: Run the suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass, none skipped.

- [ ] **Step 7: Commit**

```bash
git add -A src app tests
git commit -m "Evaluate runs and the evidence audit from the database

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The Knowledge Graph page and named-graph captions

**Files:**
- Modify: `app/rdfviz.py`, `app/explorer.py` (`html`), `app/streamlit_app.py`
- Test: `tests/test_rdfviz.py` (create), `tests/test_app.py`

**Interfaces:**
- Consumes: `kg.graphs`, `kg.get_graph`, `kg.query`, `kg.ONTOLOGY`, `kg.gold_graph_name`, `kg.answer_graph_name`, `explorer.html`, `rdfviz.short`, `rdfviz.PREFIXES`.
- Produces:
  - `rdfviz.KG_QUERIES: dict[str, str]` (dataset-wide presets for Oxigraph)
  - `rdfviz.VIS_NODE_TYPES`, `rdfviz.VIS_EDGE_TYPES`, `rdfviz.vis_graph(g, limit=400) -> dict` (keys `nodes, edges, details, truncated`)
  - `explorer.html(graph, height=720, node_types=None, edge_types=None)`
  - `page_kg()` registered as page `"Graf Pengetahuan"`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rdfviz.py`:

```python
"""Knowledge Graph page helpers: dataset-wide presets and the generic RDF graph view."""
import pytest
from rdflib import Graph, Literal

import explorer
import rdfviz
from autograde import io, kg, pipeline
from autograde.io import AG, ANS, KEY
from test_pipeline import STUB


@pytest.fixture(scope="module")
def graded_a07():
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text["Q1_A07"]
    pipeline.run_answer(ctx, "Q1_A07", text, "gold", pipeline.ui_run(), use_llm_feedback=False)


def test_every_kg_preset_runs_and_recompute_matches(graded_a07):
    for name, query in rdfviz.KG_QUERIES.items():
        kg.query(query)  # parses and runs on Oxigraph
    df = kg.query(rdfviz.KG_QUERIES["Hitung ulang skor tiap jawaban (Pers. 6) dari graf tersimpan"])
    row = df[df.ledgerGraph == kg.answer_graph_name("ui", "Q1_A07", "ledger")]
    assert float(row.score.iloc[0]) == pytest.approx(70.0)
    counts = kg.query(rdfviz.KG_QUERIES["Jumlah triple per named graph"]).set_index("graph").triples
    assert int(counts[kg.ONTOLOGY]) > 100 and int(counts[kg.gold_graph_name("Q1")]) > 0


def test_vis_graph_covers_every_triple_and_truncates():
    g = Graph()
    g.add((ANS.t1, AG.hasObject, KEY.CO2))
    g.add((ANS.t1, AG.negated, Literal(False)))
    g.add((KEY.CO2, AG.hasSubject, Literal("x")))
    vis = rdfviz.vis_graph(g)
    assert len(vis["edges"]) == 3 and not vis["truncated"]
    kinds = {n["id"]: n["kind"] for n in vis["nodes"]}
    assert kinds[str(ANS.t1)] == "ans" and kinds[str(KEY.CO2)] == "key"
    assert sum(k == "literal" for k in kinds.values()) == 2  # each literal is its own node
    assert {e["from"] for e in vis["edges"]} | {e["to"] for e in vis["edges"]} <= set(kinds)
    assert rdfviz.vis_graph(g, limit=2)["truncated"]
    page = explorer.html(vis, node_types=rdfviz.VIS_NODE_TYPES, edge_types=rdfviz.VIS_EDGE_TYPES)
    assert "Literal" in page
```

In `tests/test_app.py`, add `"Graf Pengetahuan"` to the list in `test_static_pages`.

- [ ] **Step 2: Run them to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_rdfviz.py -q`
Expected: failures on `AttributeError: module 'rdfviz' has no attribute 'KG_QUERIES'`.

- [ ] **Step 3: Let `explorer.html` take legend types**

In `app/explorer.py`, replace the first two lines of `html`:

```python
def html(graph, height=720, node_types=None, edge_types=None):
    """Self-contained page: vis-network inlined, data as JSON, details rendered with textContent (no HTML injection)."""
    data = json.dumps({"graph": graph, "nodeTypes": node_types or NODE_TYPES, "edgeTypes": edge_types or EDGE_TYPES},
                      ensure_ascii=False)
```

- [ ] **Step 4: Presets and the generic graph view in `rdfviz.py`**

Append to `app/rdfviz.py`:

```python
# ---------- knowledge graph page (Oxigraph, all named graphs) ----------

KG_QUERIES = {
    "Jumlah triple per named graph": PREFIXES + """
SELECT ?graph (COUNT(*) AS ?triples)
WHERE { GRAPH ?graph { ?s ?p ?o } }
GROUP BY ?graph
ORDER BY ?graph""",
    "Hitung ulang skor tiap jawaban (Pers. 6) dari graf tersimpan": PREFIXES + """
# One row per stored ledger graph: credits from the answer's ledger graph, weights from the question's gold graph.
SELECT ?ledgerGraph ?answer ((100 * SUM(?w * ?c)) / SUM(?w) AS ?score)
WHERE {
  GRAPH ?ledgerGraph { ?e a ag:LedgerEntry ; ag:answer ?answer ; ag:reference ?r ; ag:credit ?c . }
  GRAPH ?goldGraph { ?r ag:weight ?w . }
  FILTER (STRENDS(STR(?ledgerGraph), ":ledger"))
}
GROUP BY ?ledgerGraph ?answer
ORDER BY ?ledgerGraph""",
    "Semua entri Kontradiksi untuk satu soal": PREFIXES + """
SELECT ?ledgerGraph ?answer ?reference ?studentTriple
WHERE {
  GRAPH ?ledgerGraph { ?e ag:status ag:Kontradiksi ; ag:answer ?answer ; ag:reference ?reference ;
                          ag:contradictedBy ?studentTriple . }
  FILTER (STRSTARTS(STR(?reference), "http://example.org/autograde/key/Q1_"))   # change Q1 to another question
}
ORDER BY ?answer""",
    "Triple jawaban dari satu kalimat (PROV-O)": PREFIXES + """
SELECT ?answerGraph ?sentence ?text ?studentTriple
WHERE {
  GRAPH ?answerGraph { ?studentTriple prov:wasDerivedFrom ?sentence . ?sentence rdfs:label ?text . }
  FILTER (STRENDS(STR(?sentence), "Q1_A07_s1"))   # change to another sentence id
}""",
    "Hierarki konsep satu soal (skos:broader+)": PREFIXES + """
SELECT ?concept ?broader
WHERE { GRAPH <urn:ag:gold:Q1> { ?concept skos:broader+ ?broader . } }
ORDER BY ?concept ?broader""",
}

VIS_NODE_TYPES = {  # key: (legend label, colour, vis shape, shown by default)
    "ag": ("ag: (skema/ontologi)", "#eab308", "diamond", True),
    "key": ("key: (data dosen)", "#3b82f6", "dot", True),
    "ans": ("ans: (data mahasiswa)", "#6366f1", "dot", True),
    "other": ("IRI lain (rdf, owl, skos, prov)", "#64748b", "dot", True),
    "literal": ("Literal", "#9ca3af", "box", True),
}
VIS_EDGE_TYPES = {"triple": ("Triple RDF (label = predikat)", "#94a3b8", False, 1, True)}


def vis_graph(g, limit=400):
    """Any RDF graph for the Semantic Explorer view: IRIs and literals are nodes, each triple an edge.

    shortcut: shows the first `limit` triples (sorted); upgrade to paging if graphs grow past a few thousand."""
    namespaces = (("ag", str(io.AG)), ("key", str(io.KEY)), ("ans", str(io.ANS)))

    def kind(term):
        return next((k for k, ns in namespaces if str(term).startswith(ns)), "other")

    nodes, edges = {}, []
    triples = sorted(g)
    for i, (s, p, o) in enumerate(triples[:limit]):
        nodes.setdefault(str(s), {"id": str(s), "kind": kind(s), "label": short(s), "title": str(s)})
        if isinstance(o, Literal):
            oid = f"literal:{i}"
            text = str(short(o))
            nodes[oid] = {"id": oid, "kind": "literal", "label": text[:40], "title": text}
        else:
            oid = str(o)
            nodes.setdefault(oid, {"id": oid, "kind": kind(o), "label": short(o), "title": oid})
        edges.append({"from": str(s), "to": oid, "kind": "triple", "label": short(p), "title": str(p)})
    return {"nodes": list(nodes.values()), "edges": edges, "details": {}, "truncated": len(triples) > limit}
```

- [ ] **Step 5: The page and the captions in `streamlit_app.py`**

Add the page function before `PAGES`:

```python
def page_kg():
    st.header("Graf Pengetahuan (triple store Oxigraph)")
    st.caption("Semua graf RDF tersimpan sebagai named graph dalam satu triple store: ontologi, kunci tiap soal, "
               "dan graf jawaban/ledger tiap jawaban yang dinilai. Hanya baca.")
    graphs = pd.DataFrame(kg.graphs())
    if graphs.empty:
        st.info("Triple store kosong. Jalankan `python -m autograde db import`.")
        return
    question_of = answers_table().set_index("answer_id").question_id
    graphs["question"] = graphs.question.fillna(graphs.answer.map(question_of))
    c = st.columns(3)
    c[0].metric("Named graph", len(graphs))
    c[1].metric("Triple (total)", int(graphs.triples.sum()))
    c[2].metric("Run", graphs.run.nunique())
    st.dataframe(graphs, hide_index=True, use_container_width=True)
    name = st.selectbox("Lihat satu graf", list(graphs.name))
    g = kg.get_graph(name)
    tabs = st.tabs(["Turtle", "Graf interaktif", "Tabel triple", "SPARQL (seluruh dataset)"])
    with tabs[0]:
        ttl = g.serialize(format="turtle")
        st.download_button("Unduh Turtle", ttl, file_name=rdfviz.turtle_file_name(name), key="kg_dl")
        st.code(ttl, language="turtle")
    with tabs[1]:
        vis = rdfviz.vis_graph(g)
        if vis["truncated"]:
            st.caption(f"Menampilkan 400 dari {len(g)} triple.")
        components.html(explorer.html(vis, height=600, node_types=rdfviz.VIS_NODE_TYPES,
                                      edge_types=rdfviz.VIS_EDGE_TYPES), height=700, scrolling=False)
    with tabs[2]:
        st.dataframe(pd.DataFrame([[rdfviz.short(s), rdfviz.short(p), rdfviz.short(o)] for s, p, o in sorted(g)],
                                  columns=["subjek", "predikat", "objek"]), hide_index=True, use_container_width=True)
    with tabs[3]:
        st.caption("Graf bawaan = gabungan semua named graph; pakai `GRAPH ?g { … }` untuk melihat asal triple.")
        preset = st.selectbox("Kueri contoh", list(rdfviz.KG_QUERIES), key="kg_preset")
        query = st.text_area("SPARQL", rdfviz.KG_QUERIES[preset], height=260, key=f"kg_q_{preset}")
        if st.button("Jalankan kueri", key="kg_run"):
            try:
                result = kg.query(query)
            except Exception as e:
                st.error(f"Kueri gagal: {e}")
                return
            if isinstance(result, str):
                st.code(result or "# (graf kosong)", language="turtle")
            else:
                st.dataframe(result.map(lambda v: rdfviz.short(v) if isinstance(v, str) else v),
                             hide_index=True, use_container_width=True)
                st.caption(f"{len(result)} baris")
```

Register it: `PAGES = {..., "Evaluasi": page_evaluation, "Graf Pengetahuan": page_kg}`.

Named-graph captions on the existing graph views:
- `page_ontology`, right after its first `st.caption(...)`: `st.caption(f"Named graph: \`{kg.ONTOLOGY}\`")`.
- `page_question`, after `view = st.radio(...)`: `st.caption(f"Named graph: \`{kg.gold_graph_name(qid)}\`")`.
- `show_result`, tab 2 (alignment) caption: append ` Dibaca dari \`{kg.answer_graph_name(res['run_id'], answer_id, 'answer')}\`.` to the existing caption string (make it an f-string).
- `page_explorer`, after the `st.caption(f"{len(graph['nodes'])} node ...")` line: `st.caption(f"Named graph: \`{kg.gold_graph_name(qid)}\` + graf answer/ledger tiap jawaban terpilih.")`.

- [ ] **Step 6: Run the suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A app tests
git commit -m "Add the Knowledge Graph page and named-graph captions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Pellet before/after view and the visible SPARQL parity check

**Files:**
- Modify: `app/rdfviz.py`, `app/streamlit_app.py` (`show_result`, `show_reasoning`)
- Test: `tests/test_rdfviz.py`

**Interfaces:**
- Consumes: `kg.get_graph`, `kg.answer_graph_name`, `kg.gold_graph_name`, `io.ontology_relations()` (returns `rels, eq, inc` with `eq[r]` the equivalence class including `r`, and `inc` a set of `frozenset` pairs), `ledger.recompute_rows`, `ledger.RECOMPUTE_QUERY`.
- Produces: `rdfviz.swrl_rule(t_pred, r_pred, negated, eq, inc) -> int | None`, `rdfviz.pellet_dots(g, eq, inc) -> (before_dot, after_dot)`; `show_reasoning(ctx, answer_id, res)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rdfviz.py`:

```python
def test_swrl_rule_labels():
    eq = {"menyerap": {"menyerap", "menggunakan"}, "menggunakan": {"menyerap", "menggunakan"}}
    inc = {frozenset(("menghasilkan", "mengonsumsi"))}
    assert rdfviz.swrl_rule("menghasilkan", "mengonsumsi", False, eq, inc) == 1
    assert rdfviz.swrl_rule("menghasilkan", "menghasilkan", True, eq, inc) == 2
    assert rdfviz.swrl_rule("menyerap", "menggunakan", True, eq, inc) == 3
    assert rdfviz.swrl_rule("menyerap", "menggunakan", False, eq, inc) is None


@pytest.mark.parametrize("answer_id, triple, ref, rule", [("Q1_A08", "Q1_A08_t4", "Q1_R2", 1),
                                                          ("Q1_S03", "Q1_S03_t1", "Q1_R5", 2)])
def test_pellet_before_after(answer_id, triple, ref, rule):
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text[answer_id]
    pipeline.run_answer(ctx, answer_id, text, "gold", pipeline.ui_run(), use_llm_feedback=False)
    g = kg.get_graph(kg.answer_graph_name("ui", answer_id, "answer"), kg.gold_graph_name("Q1"))
    _, eq, inc = io.ontology_relations()
    before, after = rdfviz.pellet_dots(g, eq, inc)
    assert "alignedSubject" in before and "contradicts" not in before
    assert f'"{triple}" -> "{ref}" [label="ag:contradicts\\n(Aturan {rule})"' in after
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `conda run -n semantic_web pytest tests/test_rdfviz.py -q`
Expected: failures on `AttributeError: module 'rdfviz' has no attribute 'swrl_rule'`.

- [ ] **Step 3: Write the DOT builders in `rdfviz.py`**

Append to `app/rdfviz.py`:

```python
# ---------- Pellet before/after ----------

def swrl_rule(t_pred, r_pred, negated, eq, inc):
    """Which SWRL rule explains `t ag:contradicts r`: 1 incompatible predicate, not negated; 2 same predicate,
    negated; 3 equivalent predicate, negated. A display aid derived from the inputs; not stored."""
    if not negated and frozenset((t_pred, r_pred)) in inc:
        return 1
    if negated and t_pred == r_pred:
        return 2
    if negated and r_pred in eq.get(t_pred, ()):
        return 3
    return None


def pellet_dots(g, eq, inc):
    """(before, after) DOT from a stored answer graph plus its gold graph.

    Before: the facts Python asserted for Pellet (alignment, negation, predicates and their ontology relations).
    After: the same plus the inferred ag:contradicts edges, labelled with the SWRL rule that fired."""
    pred = {s: name(o) for s, o in g.subject_objects(AG.hasPredicate)}
    negated = {s: bool(o.toPython()) for s, o in g.subject_objects(AG.negated)}
    aligned = sorted(set(g.subject_objects(AG.alignedSubject)) & set(g.subject_objects(AG.alignedObject)))
    contra = sorted(g.subject_objects(AG.contradicts))
    nodes = sorted({t for t, _ in aligned} | {r for _, r in aligned})
    preds = sorted({pred[n] for n in nodes})
    lines = ['digraph { rankdir=LR; node [fontname=Helvetica, fontsize=10]; edge [fontname=Helvetica, fontsize=9];']
    for n in nodes:
        is_student = n in negated
        neg = "NOT " if negated.get(n) else ""
        fill = "#e0e7ff" if is_student else "#dbeafe"
        lines.append(f'"{name(n)}" [shape=box, style="rounded,filled", fillcolor="{fill}", '
                     f'label="{esc(name(n))}\\n{neg}{esc(pred[n])}"];')
        lines.append(f'"{name(n)}" -> "ag:{pred[n]}" [label="hasPredicate", color="#94a3b8", fontcolor="#64748b"];')
    for p in preds:
        lines.append(f'"ag:{p}" [shape=diamond, style=filled, fillcolor="#fef3c7", label="ag:{esc(p)}"];')
    for i, a in enumerate(preds):
        for b in preds[i + 1:]:
            if frozenset((a, b)) in inc:
                lines.append(f'"ag:{a}" -> "ag:{b}" [dir=none, color="#c62828", label="incompatibleWith"];')
            elif b in eq.get(a, ()):
                lines.append(f'"ag:{a}" -> "ag:{b}" [dir=none, color="#1d4ed8", label="equivalentPredicate"];')
    for t, r in aligned:
        lines.append(f'"{name(t)}" -> "{name(r)}" [label="alignedSubject +\\nalignedObject", color="#a855f7", '
                     f'style=dashed];')
    before = "\n".join(lines + ["}"])
    inferred = [f'"{name(t)}" -> "{name(r)}" [label="ag:contradicts\\n(Aturan '
                f'{swrl_rule(pred[t], pred[r], negated.get(t, False), eq, inc)})", color="#dc2626", '
                f'fontcolor="#dc2626", style=dashed, penwidth=2.5];' for t, r in contra]
    return before, "\n".join(lines + inferred + ["}"])
```

- [ ] **Step 4: Show both views in the app**

In `app/streamlit_app.py`:

- In `show_result`, change the call in tab 3 to `show_reasoning(ctx, answer_id, res)`, and right after the five `c[...].metric(...)` lines add:

```python
    with st.expander("Bukti hitung ulang SPARQL (dibaca dari graf tersimpan)"):
        gold_name, _, ledger_name = rdfviz.answer_graph_names(qid, res["run_id"], answer_id)
        rows = ledger_mod.recompute_rows(kg.get_graph(ledger_name), kg.get_graph(gold_name), ctx.params["lambda"])
        st.code(ledger_mod.RECOMPUTE_QUERY.strip(), language="sparql")
        st.dataframe(pd.DataFrame([{"answer": rdfviz.short(r.ans), "skor (sebelum dipotong di 0)": float(r.raw.toPython())}
                                   for r in rows]), hide_index=True)
        st.caption(f"Skor Python = {sc.score:.4f} · skor SPARQL dari triple store = {sc.sparql_score:.4f} "
                   f"{'✓' if ok else '✗'} · graf: `{ledger_name}` + `{gold_name}`")
```

- Change `def show_reasoning(ctx, res):` to `def show_reasoning(ctx, answer_id, res):` and, just before the `if res["log"]:` block at its end, add:

```python
    st.markdown("**5 · Pellet: sebelum dan sesudah penalaran**")
    if aligned:
        answer_name = kg.answer_graph_name(res["run_id"], answer_id, "answer")
        g = kg.get_graph(answer_name, kg.gold_graph_name(ctx.qid))
        _, eq, inc = io.ontology_relations()
        before, after = rdfviz.pellet_dots(g, eq, inc)
        c = st.columns(2)
        c[0].caption("Sebelum: fakta yang ditegaskan Python (masukan Pellet)")
        c[0].graphviz_chart(before)
        c[1].caption("Sesudah: + `ag:contradicts` yang disimpulkan (merah putus-putus, dengan nomor aturan SWRL)")
        c[1].graphviz_chart(after)
        st.caption(f"Dibaca dari named graph `{answer_name}` + `{kg.gold_graph_name(ctx.qid)}`.")
    else:
        st.caption("Tidak ada pasangan selaras (σ ≥ τh), jadi Pellet tidak punya masukan untuk aturan kontradiksi.")
```

- [ ] **Step 5: Run the suite**

Run: `conda run -n semantic_web pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A app tests
git commit -m "Show Pellet's input and inferences side by side, and the SPARQL parity evidence

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Guard test, documentation and acceptance

**Files:**
- Create: `tests/test_no_file_reads.py`
- Modify: `src/autograde/gold.py` (docstring if still mentioning files), `README.md`, `PROTOTYPE_PLAN.md`, `docs/DECISIONS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing new; enforces spec Section 3's "only `importer.py` reads `data/`".

- [ ] **Step 1: Write the guard test**

Create `tests/test_no_file_reads.py`:

```python
"""After `db import`, only importer.py may read data/ or the old run folders (spec, section 3)."""
import re

from autograde import io

BANNED = re.compile(r'question_dir|annotation_path|runs_dir|"data" /|"outputs" / "(runs|ui)"'
                    r'|"(gold|answer|ledger)[a-z_]*\.ttl"')


def test_no_module_reads_the_old_files():
    files = [p for p in (io.ROOT / "src" / "autograde").glob("*.py") if p.name != "importer.py"]
    files += list((io.ROOT / "app").glob("*.py"))
    hits = [f"{p.relative_to(io.ROOT)}:{i}: {line.strip()}"
            for p in files for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if BANNED.search(line)]
    assert hits == []
```

- [ ] **Step 2: Run it and fix every hit**

Run: `conda run -n semantic_web pytest tests/test_no_file_reads.py -q`
Expected: PASS. If it fails, each hit names a file and line: replace that read with the matching `db`/`kg` call from Tasks 5–7 (do not weaken the regex).

Then check the prose for stale file names: `grep -n "\.ttl\|run\.json\|scores\.csv\|overrides\.yaml" src/autograde/*.py app/*.py`. Only `importer.py` and the Turtle download file names (`turtle_file_name`) may remain. Reword any docstring, comment or UI caption that still describes files (for example a `gold.ttl` mention) to the named graph (`urn:ag:gold:<qid>`).

- [ ] **Step 3: Update the README**

In `README.md`, replace the "Run" section's code block with:

```bash
conda run -n semantic_web pytest                                   # all tests, offline (they build their own temp database)
python -m autograde db import                      # once: data/ -> db/autograde.sqlite + db/kg/ (Oxigraph)
python -m autograde gold --question Q1             # re-validate a key -> named graph urn:ag:gold:Q1 + docs/gold_Q1_review.md
python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback   # offline demo
python -m autograde evaluate --run <run_id>        # report saved with the run; figures in outputs/reports/<run_id>/
streamlit run app/streamlit_app.py
```

and add after it:

```markdown
Storage: everything lives in `db/` (SQLite for records, an Oxigraph triple store with one named graph per document). Set `AUTOGRADE_DB_DIR` to keep it elsewhere. `data/` is only read by `db import`; re-import with `db import --replace` after editing files there. A run can be resumed with `run ... --run-id <id>`. Lecturer corrections: `override --run <id> --file overrides.yaml`; evidence audit: `audit-template --run <id>`, fill the CSV, then `audit-import --file <csv>`.
```

Change the sentence `Real data goes in data/answers/answers.csv, ...` to start with `Before import, real data goes in` and keep the rest.

- [ ] **Step 4: Point the plan and the decisions log at the new layout**

At the top of `PROTOTYPE_PLAN.md` Section 2 ("Repository layout"), insert:

```markdown
> **Storage changed on 2026-10-24.** Records and RDF graphs now live in a database (SQLite + Oxigraph), not in `data/` and `outputs/runs/`. See `docs/superpowers/specs/2026-10-24-persistence-foundation-design.md`. The layout below is the original prototype's.
```

Append to `docs/DECISIONS.md`:

```markdown
## 2026-10-24 — Database storage (sub-project 1 of 4)

- Records (courses, questions with rubric and gold key as JSON, answers, human scores, runs, results, overrides, evidence audit) live in SQLite; every RDF graph lives in an embedded Oxigraph store as a named graph (`urn:ag:ontology`, `urn:ag:gold:<qid>`, `urn:ag:run:<run>:<answer>:{answer|ledger|ledger_corrected}`). Spec: `docs/superpowers/specs/2026-10-24-persistence-foundation-design.md`.
- The SPARQL recompute now reads the ledger and gold graphs back from the store, so it audits what was persisted.
- Oxigraph stores decimals canonically (`"2.0"` comes back as `"2"`); scores are unaffected because SPARQL compares numeric values.
- Runs are resumable: re-running a run id skips answers that already have a result row. Evaluation figures go to `outputs/reports/<run>/`; the report text is stored with the run.
```

- [ ] **Step 5: Acceptance**

Run each and check the expected result:

1. `conda run -n semantic_web pytest -q`: all pass.
2. `mv db db.bak 2>/dev/null; conda run -n semantic_web python -m autograde db import`: prints the import counts (1 question, 7 answers).
3. `conda run -n semantic_web python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback --run-id accept`, then `evaluate --run accept`, `recompute --run accept --answer Q1_A07`, and `override --run accept` (with no overrides it prints nothing and exits 0): all succeed. The report starts with `SYNTHETIC DATA`.
4. `streamlit run app/streamlit_app.py`: open every page. On *Nilai Jawaban*, grade Q1_A08 and check the parity expander and the Pellet before/after graphs (Aturan 1). On *Graf Pengetahuan*, see the `accept` run's graphs, open one as Turtle, as an interactive graph and as a table, and run every preset. Confirm that `data/` is not read: `mv data data.off`, reload the app, use it, then `mv data.off data`.
5. Restore your old database if step 2 moved one: `rm -rf db && mv db.bak db` (skip if there was none).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Guard against file reads; document the database layout

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
