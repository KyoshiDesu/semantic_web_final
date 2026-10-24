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
