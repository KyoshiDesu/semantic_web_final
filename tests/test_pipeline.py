import pytest

from autograde import db, io, kg, ledger, pipeline
from autograde.normalize import make_sim

STUB = lambda a, b: 1.0 if a == b else (0.70 if {a, b} == {"makanan", "glukosa"} else 0.0)


@pytest.fixture
def ctx():
    return pipeline.Context.load("Q1", params={"tau_h": 0.8, "tau_l": 0.6, "delta": 0.5, "lambda": 0.0},
                                 reasoner="sparql", cosine=STUB)


def test_broader_similarity_must_be_partial(ctx):
    import dataclasses
    bad = dataclasses.replace(ctx, broader_similarity=0.9)
    with pytest.raises(ValueError, match="partial band"):
        pipeline.grade(bad, "Q1_A07", [])


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
