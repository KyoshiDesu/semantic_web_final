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
