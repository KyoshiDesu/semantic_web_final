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
