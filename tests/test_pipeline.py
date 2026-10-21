import pytest

from autograde import io, ledger, pipeline
from autograde.normalize import make_sim

STUB = lambda a, b: 1.0 if a == b else (0.70 if {a, b} == {"makanan", "glukosa"} else 0.0)


@pytest.fixture
def ctx():
    return pipeline.Context.load("Q1", params={"tau_h": 0.8, "tau_l": 0.6, "delta": 0.5, "lambda": 0.0},
                                 reasoner="sparql", cosine=STUB)


def test_run_answer_gold_mode_writes_everything(ctx, tmp_path):
    text = io.load_yaml(io.ROOT / "tests" / "fixtures" / "worked_example.yaml")["text"]
    res = pipeline.run_answer(ctx, "Q1_A07", text, "gold", tmp_path, use_llm_feedback=False)
    assert res["score"].score == pytest.approx(70.0) and res["score"].sparql_score == pytest.approx(70.0)
    for name in ["ledger.json", "ledger.csv", "ledger.ttl", "answer.ttl", "score.json", "feedback.json",
                 "sentences.json", "student_triples.json", "extraction_log.jsonl"]:
        assert (tmp_path / name).exists(), name


def test_parity_failure_raises(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "recompute_sparql", lambda *a: 12.3)
    with pytest.raises(pipeline.ParityError):
        pipeline.run_answer(ctx, "Q1_A07", "Tumbuhan menyerap sinar matahari.", "gold", tmp_path, use_llm_feedback=False)
