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
