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
