"""LMS CSV imports: preview, answers (wide and long), lecturer scores, and the mistakes people make."""
import json

from autograde import db
from autograde.api import deps


def demo_course(client):
    return next(c for c in client.get("/api/courses").json() if c["code"] == "DEMO")["id"]


def post(client, path, text, mapping, **params):
    return client.post(path, params=params, files={"file": ("lms.csv", text.encode("utf-8"))},
                       data={"mapping": json.dumps(mapping)})


WIDE = "nim,nama,jwb\n2201,Ani,Tumbuhan memakai cahaya matahari.\n2202,Budi,-\n"
WIDE_MAP = {"id_col": "nim", "name_cols": ["nama"], "columns": {"Q1": {"column": "jwb"}}}


def test_preview_reads_semicolons_and_a_bom(client):
    text = "﻿nim;nama;jawaban Q1\n123;Ani;tumbuhan menggunakan cahaya\n"
    r = client.post("/api/imports/preview", files={"file": ("x.csv", text.encode("utf-8"))}).json()
    assert r["columns"] == ["nim", "nama", "jawaban Q1"] and r["count"] == 1
    assert r["rows"] == [["123", "Ani", "tumbuhan menggunakan cahaya"]]


def test_import_wide_answers_dry_run_then_for_real(client):
    course = demo_course(client)
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP, dry_run=True).json()
    assert (r["new"], r["added"], r["blank"], r["existing"]) == (1, 0, 1, [])
    assert "Q1_2201" not in db.answer_ids(["Q1"])
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP).json()
    assert r["added"] == 1 and r["answers"][0]["answer_id"] == "Q1_2201"
    r = post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP).json()
    assert r["added"] == 0 and r["existing"] == ["Q1_2201"]
    students = client.get(f"/api/courses/{course}/students").json()
    assert ["2201", "Ani", 1] in students["rows"]


def test_import_long_answers(client):
    text = "nim,soal,jawaban\n2203,Q1,Daun menyerap karbon dioksida.\n2203,Q9,lain\n"
    mapping = {"id_col": "nim", "columns": {"Q1": {"column": "jawaban", "filter_column": "soal",
                                                    "filter_value": "Q1"}}}
    r = post(client, f"/api/courses/{demo_course(client)}/answers", text, mapping).json()
    assert r["added"] == 1 and r["answers"][0]["text"] == "Daun menyerap karbon dioksida."


def test_mapping_mistakes_are_422(client):
    course = demo_course(client)
    r = post(client, f"/api/courses/{course}/answers", WIDE, {**WIDE_MAP, "columns": {"Q1": {"column": "nope"}}})
    assert r.status_code == 422 and "'nope'" in r.json()["details"][0]
    other = client.post("/api/courses", json={"code": "C2", "name": "Lain"}).json()["id"]
    r = post(client, f"/api/courses/{other}/answers", WIDE, WIDE_MAP)
    assert r.status_code == 422 and "Q1" in r.json()["details"][0]
    r = client.post(f"/api/courses/{course}/answers", files={"file": ("x.csv", WIDE.encode())},
                    data={"mapping": "{not json"})
    assert r.status_code == 422
    half = {"id_col": "nim", "columns": {"Q1": {"column": "jwb", "filter_column": "soal"}}}
    assert post(client, f"/api/courses/{course}/answers", WIDE, half).status_code == 422


def test_import_scores(client):
    course = demo_course(client)
    post(client, f"/api/courses/{course}/answers", WIDE, WIDE_MAP)
    mapping = {"id_col": "nim", "question_id": "Q1", "columns": {"_total": "total"}, "rater_id": "D1"}
    r = post(client, f"/api/courses/{course}/scores", "nim,total\n2201,\"85,5\"\n", mapping).json()
    assert r["added"] == 1 and r["rows"] == [["Q1_2201", "D1", "_total", 85.5]]
    scores = db.human_scores(include_synthetic=True)
    assert scores[scores.answer_id == "Q1_2201"].score_0_100.tolist() == [85.5]
    r = post(client, f"/api/courses/{course}/scores", "nim,total\n2201,150\n", mapping)
    assert r.status_code == 422 and "outside 0-100" in r.json()["details"][0]


def test_upload_over_the_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(deps, "MAX_UPLOAD", 10)
    r = client.post("/api/imports/preview", files={"file": ("x.csv", b"a,b\n" * 10)})
    assert r.status_code == 413 and r.json()["error"] == "too_large"
