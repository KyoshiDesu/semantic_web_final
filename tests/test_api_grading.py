"""Grading an assessment through the API: background jobs, review, corrections and the gated exports."""
import threading
import time

from fastapi.testclient import TestClient

from autograde import db, pipeline
from autograde.api import jobs
from autograde.api.app import create_app


def demo_assessment(client):
    course = next(c for c in client.get("/api/courses").json() if c["code"] == "DEMO")["id"]
    return client.get(f"/api/courses/{course}/assessments").json()[0]["id"]


def wait(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} is still running")


def column(status, name):
    i = status["columns"].index(name)
    return {row[0]: row[i] for row in status["rows"]}  # keyed by answer_id, the first column


def test_grade_review_correct_and_export(client):
    aid = demo_assessment(client)
    st = client.get(f"/api/assessments/{aid}/status").json()
    assert st["counts"] == {"belum dinilai": 7} and not st["ready"]
    assert set(column(st, "name").values()) == {None}  # demo answers have no student name: null, not NaN
    r = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert r.status_code == 202 and r.json()["total"] == 7
    job = wait(client, r.json()["id"])
    assert (job["status"], job["done"], job["failures"], job["current"]) == ("done", 7, [], None)
    st = client.get(f"/api/assessments/{aid}/status").json()
    run_id = st["run_id"]
    assert st["counts"] == {"dinilai": 7} and "Q1_A08" not in st["approvable"]  # A08 has a contradiction

    r = client.get(f"/api/assessments/{aid}/exports/grades.csv")
    assert r.status_code == 409 and "dinilai" in r.json()["message"]
    draft = client.get(f"/api/assessments/{aid}/exports/grades.csv?draft=true")
    assert draft.status_code == 200 and draft.text.lstrip("﻿").startswith("# DRAF")

    assert client.post(f"/api/assessments/{aid}/review/bulk", json={"by": "  "}).status_code == 422
    bulk = client.post(f"/api/assessments/{aid}/review/bulk", json={"by": "DS"}).json()["reviewed"]
    assert sorted(bulk) == sorted(st["approvable"])

    ledger = db.result(run_id, "Q1_A08")["ledger"]
    ref = next(e["reference_id"] for e in ledger if e["status"] == "CONTRADICTED")
    before = db.result(run_id, "Q1_A08")["score"]["score"]
    url = f"/api/results/{run_id}/Q1_A08"
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": "R99", "status": "MATCHED", "reason": "x"}]}).status_code == 422
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MATCHED", "reason": " "}]}).status_code == 422
    r = client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MATCHED", "reason": "dibaca ulang"}]})
    sc = r.json()["score"]
    assert r.status_code == 200 and sc["score"] > before and abs(sc["score"] - sc["sparql_score"]) < 1e-9

    for answer_id, status in column(client.get(f"/api/assessments/{aid}/status").json(), "status").items():
        if status == "dinilai":
            assert client.post(f"/api/results/{run_id}/{answer_id}/review", json={"by": "DS"}).status_code == 200
    assert client.post(f"{url}/review", json={"by": "DS"}).status_code == 409  # already reviewed
    assert client.post(f"{url}/corrections", json={"by": "DS", "corrections": [
        {"reference_id": ref, "status": "MISSING", "reason": "x"}]}).status_code == 409
    r = client.get(f"/api/assessments/{aid}/exports/grades.csv")
    assert r.status_code == 200 and r.text.lstrip("﻿").startswith("external_id,name,Q1")
    assert 'filename="DEMO_' in r.headers["content-disposition"]
    assert client.get(f"/api/assessments/{aid}/exports/feedback.csv").status_code == 200

    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])  # the key is edited
    assert client.get(f"/api/assessments/{aid}/status").json()["counts"] == {"usang": 7}
    r = client.post(f"/api/results/{run_id}/Q1_A07/review", json={"by": "DS"})
    assert r.status_code == 409 and "grade it again" in r.json()["message"]
    job = wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "stale"}).json()["id"])
    assert job["done"] == 7 and client.get(f"/api/assessments/{aid}/status").json()["counts"] == {"dinilai": 7}
    assert client.post(f"/api/assessments/{aid}/grading", json={"which": "stale"}).status_code == 422


def test_start_returns_at_once_and_one_job_at_a_time(client, monkeypatch):
    aid = demo_assessment(client)
    gate, orig = threading.Event(), pipeline.grade_assessment_answer

    def held(run_id, answer, contexts, use_llm_feedback=False):
        gate.wait(30)
        return orig(run_id, answer, contexts, use_llm_feedback)

    monkeypatch.setattr(pipeline, "grade_assessment_answer", held)
    r = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert r.status_code == 202 and r.json()["status"] == "running"  # returned while the thread waits
    second = client.post(f"/api/assessments/{aid}/grading", json={"which": "new"})
    assert second.status_code == 409 and str(r.json()["id"]) in second.json()["message"]
    gate.set()
    assert wait(client, r.json()["id"])["status"] == "done"


def test_one_failing_answer_does_not_stop_the_class(client, monkeypatch):
    aid = demo_assessment(client)
    orig = pipeline.grade_assessment_answer

    def flaky(run_id, answer, contexts, use_llm_feedback=False):
        if answer.answer_id == "Q1_A07":
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return orig(run_id, answer, contexts, use_llm_feedback)

    monkeypatch.setattr(pipeline, "grade_assessment_answer", flaky)
    job = wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()["id"])
    assert job["status"] == "done" and job["done"] == 7
    assert job["failures"] == [{"answer_id": "Q1_A07", "error": "ANTHROPIC_API_KEY is not set"}]
    st = client.get(f"/api/assessments/{aid}/status").json()
    assert st["counts"] == {"dinilai": 6, "belum dinilai": 1}


def test_cancel(client):
    aid = demo_assessment(client)
    run_id = pipeline.assessment_run(aid)
    job_id = db.create_job(aid, run_id, "new", False, ["Q1_A07", "Q1_A08"])
    jobs._cancel[job_id] = threading.Event()
    jobs._cancel[job_id].set()
    jobs.run_job(job_id)
    j = db.job(job_id)
    assert (j["status"], j["done"]) == ("cancelled", 0) and db.result(run_id, "Q1_A07") is None
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409  # not running any more
    orphan = db.create_job(aid, run_id, "new", False, ["Q1_A07"])  # running, but no thread in this process
    assert client.post(f"/api/jobs/{orphan}/cancel").json()["status"] == "interrupted"
    assert client.get("/api/jobs/999").status_code == 404


def test_restart_marks_the_job_interrupted_and_resuming_skips_graded_answers(client):
    aid = demo_assessment(client)
    run_id = pipeline.assessment_run(aid)
    job_id = db.create_job(aid, run_id, "new", False, ["Q1_A07", "Q1_A08", "Q1_A09"])
    answers = {a.answer_id: a for a in db.assessment_answers(aid).itertuples()}
    for a in ("Q1_A07", "Q1_A08"):  # graded before the server stopped
        pipeline.grade_assessment_answer(run_id, answers[a], {"Q1": jobs.context("Q1")})
    with TestClient(create_app(), base_url="http://127.0.0.1") as restarted:
        assert restarted.get(f"/api/jobs/{job_id}").json()["status"] == "interrupted"
        r = restarted.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()
        assert r["total"] == 5 and not {"Q1_A07", "Q1_A08"} & set(r["answer_ids"])
        wait(restarted, r["id"])


def test_context_reloads_after_the_key_is_edited(client):
    first = jobs.context("Q1")
    assert jobs.context("Q1") is first
    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    assert jobs.context("Q1") is not first and len(jobs._contexts) == 1


def test_status_names_the_assessment_and_its_latest_job(client):
    aid = demo_assessment(client)
    st = client.get(f"/api/assessments/{aid}/status").json()
    assert st["assessment"]["id"] == aid and st["course"]["code"] == "DEMO" and st["job"] is None
    job = wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()["id"])
    assert client.get(f"/api/assessments/{aid}/status").json()["job"]["id"] == job["id"]


def test_answer_search(client):
    aid = demo_assessment(client)
    rows = client.get("/api/answers").json()
    assert len(rows) == 7 and {r["status"] for r in rows} == {"belum dinilai"}
    assert rows[0]["triple"] is None and rows[0]["name"] is None and rows[0]["text"]
    wait(client, client.post(f"/api/assessments/{aid}/grading", json={"which": "new"}).json()["id"])
    contra = client.get("/api/answers", params={"filter": "contradiction"}).json()
    assert [r["answer_id"] for r in contra] == ["Q1_A08", "Q1_S03"]
    assert contra[0]["triple"]["contradicts"] == "key:Q1_R2" and contra[0]["run_id"] == f"assessment-{aid}"
    assert [r["answer_id"] for r in client.get("/api/answers", params={"filter": "flagged"}).json()] == \
        ["Q1_A07", "Q1_A08"]
    s01 = client.get("/api/answers", params={"q": "glukosa oksigen dilepaskan"}).json()
    assert [r["answer_id"] for r in s01] == ["Q1_S01"] and s01[0]["triple"]["contradicts"] is None
    assert len(client.get("/api/answers", params={"q": "karbon", "limit": 2}).json()) == 2
    assert client.get("/api/answers", params={"filter": "corrected"}).json() == []
    assert client.get("/api/answers", params={"filter": "nope"}).status_code == 422
