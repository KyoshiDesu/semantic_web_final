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


def courses():
    with tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM course ORDER BY code")]


def assessments(course_id):
    with tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM assessment WHERE course_id = ? ORDER BY name", (course_id,))]


def questions(assessment_id=None):
    sql, args = "SELECT id FROM question", []
    if assessment_id is not None:
        sql, args = sql + " WHERE assessment_id = ?", [assessment_id]
    with tx() as c:
        return [r[0] for r in c.execute(sql + " ORDER BY id", args)]


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


def answer_ids(question_ids):
    question_ids = list(question_ids)
    with tx() as c:
        return {r[0] for r in c.execute(f"SELECT id FROM answer WHERE question_id IN ({', '.join('?' * len(question_ids))})",
                                        question_ids)}


def students(course_id):
    with tx() as c:
        rows = [tuple(r) for r in c.execute(
            "SELECT s.external_id, s.name, COUNT(a.id) FROM student s LEFT JOIN answer a ON a.student_id = s.id "
            "WHERE s.course_id = ? GROUP BY s.id ORDER BY s.external_id", (course_id,))]
    return pd.DataFrame(rows, columns=["external_id", "name", "answers"])


def import_course_answers(course_id, rows):
    """Students are created on first sight; a later import fills a missing name but never overwrites one."""
    with tx() as c:
        c.executemany("INSERT INTO student (course_id, external_id, name) VALUES (?, ?, ?) "
                      "ON CONFLICT (course_id, external_id) DO UPDATE SET name = COALESCE(student.name, excluded.name)",
                      [(course_id, r["external_id"], r.get("name") or None) for r in rows])
        ids = dict(c.execute("SELECT external_id, id FROM student WHERE course_id = ?", (course_id,)).fetchall())
        c.executemany("INSERT INTO answer (id, question_id, student_id, text, split, source) VALUES (?, ?, ?, ?, ?, ?)",
                      [(r["answer_id"], r["question_id"], ids[r["external_id"]], r["text"], r["split"], r["source"])
                       for r in rows])


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


def add_human_scores(df, replace=False):
    with tx() as c:
        c.executemany(f"INSERT {'OR REPLACE ' if replace else ''}INTO human_score "
                      "(answer_id, rater_id, criterion, score_0_100) VALUES (?, ?, ?, ?)",
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
