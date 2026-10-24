"""Assessment status, review gate and exports on the DEMO assessment (7 synthetic, annotated Q1 answers)."""
import io as _io

import pandas as pd
import pytest

from autograde import db, grades, importer, pipeline
from test_pipeline import STUB


@pytest.fixture
def graded(fresh_db, monkeypatch):
    importer.import_files()
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    assessment = db.assessments(db.courses()[0]["id"])[0]["id"]
    run_id = pipeline.assessment_run(assessment)
    return assessment, run_id


def grade(run_id, assessment, ids=None):
    contexts = {}
    for a in db.assessment_answers(assessment).itertuples():
        if ids is None or a.answer_id in ids:
            pipeline.grade_assessment_answer(run_id, a, contexts)


def test_status_transitions_and_gate(graded):
    assessment, run_id = graded
    t = grades.status_table(assessment, run_id)
    assert len(t) == 7 and set(t.status) == {"belum dinilai"} and not grades.ready(t)
    grade(run_id, assessment)
    t = grades.status_table(assessment, run_id)
    assert set(t.status) == {"dinilai"}
    approvable = grades.bulk_approvable(t)
    flagged = t[(t.flagged > 0) | (t.contradictions > 0)].answer_id.tolist()
    assert "Q1_A08" in flagged and sorted(approvable + flagged) == sorted(t.answer_id)  # A08 has a contradiction
    db.mark_reviewed(run_id, t.answer_id, "DS")
    t = grades.status_table(assessment, run_id)
    assert grades.ready(t) and set(t.reviewed_by) == {"DS"}
    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])  # key edited
    t = grades.status_table(assessment, run_id)
    assert set(t.status) == {"usang"} and not grades.ready(t)
    grade(run_id, assessment, ["Q1_A07"])
    t = grades.status_table(assessment, run_id).set_index("answer_id")
    assert t.status["Q1_A07"] == "dinilai" and t.status["Q1_A08"] == "usang"


def test_exports(graded):
    assessment, run_id = graded
    grade(run_id, assessment, ["Q1_A07", "Q1_A08"])
    db.add_overrides([{"answer_id": "Q1_A07", "reference_id": "R3", "status": "MATCHED", "by": "DS",
                       "date": "2026-10-24", "reason": "air disebut"}])
    pipeline.apply_corrections(run_id, "Q1_A07")
    t = grades.status_table(assessment, run_id)
    a07 = t.set_index("answer_id").loc["Q1_A07"]
    assert a07.score == pytest.approx(70.0) and a07.final == pytest.approx(90.0)
    text = grades.grades_csv(t, ["Q1", "Q2"], draft=True)
    assert text.startswith(grades.DRAFT_MARK)
    df = pd.read_csv(_io.StringIO(text), comment="#").set_index("external_id")
    assert list(df.columns) == ["name", "Q1", "Q2", "rata_rata", "status"]
    assert df.Q1["Q1_A07"] == 90.0 and pd.isna(df.Q2["Q1_A07"]) and df.rata_rata["Q1_A07"] == 45.0
    assert pd.isna(df.Q1["Q1_S01"]) and df.status["Q1_A07"] == "0/1 ditinjau"
    assert not grades.grades_csv(t, ["Q1"]).startswith("#")
    fb = pd.read_csv(_io.StringIO(grades.feedback_csv(t, run_id))).set_index("external_id")
    assert sorted(fb.index) == ["Q1_A07", "Q1_A08"]
    assert fb.ringkasan["Q1_A07"].startswith("Skor: 90.0")  # rebuilt from the corrected ledger
