"""The API shell: courses, error mapping, the security checks, the web mount and the serve command."""
from fastapi.testclient import TestClient

from autograde import cli, db, kg
from autograde.api.app import create_app


def test_courses_and_assessments(client):
    r = client.post("/api/courses", json={"code": " SW1 ", "name": "Semantic Web"})
    assert r.status_code == 201 and r.json()["code"] == "SW1"
    course = r.json()["id"]
    assert client.post("/api/courses", json={"code": "SW1", "name": "Again"}).status_code == 409
    assert client.post(f"/api/courses/{course}/assessments", json={"name": "UTS"}).status_code == 201
    assert client.post(f"/api/courses/{course}/assessments", json={"name": "UTS"}).status_code == 409
    assert [(a["name"], a["questions"]) for a in client.get(f"/api/courses/{course}/assessments").json()] == \
        [("UTS", [])]
    assert client.get(f"/api/courses/{course}/students").json() == \
        {"columns": ["external_id", "name", "answers"], "rows": []}
    assert {"DEMO", "SW1"} <= {c["code"] for c in client.get("/api/courses").json()}


def test_unknown_ids_and_invalid_bodies(client):
    r = client.get("/api/courses/999/assessments")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "message": "unknown course 999", "details": []}
    r = client.post("/api/courses", json={"code": "  ", "name": "x"})
    assert r.status_code == 422 and r.json()["error"] == "invalid" and r.json()["details"][0].startswith("body.code")


def test_store_busy_and_unexpected_errors(client, monkeypatch):
    def busy():
        raise kg.KGBusyError("the knowledge graph store is in use by another process")

    monkeypatch.setattr(db, "courses", busy)
    r = client.get("/api/courses")
    assert r.status_code == 503 and r.headers["retry-after"] == "2" and r.json()["error"] == "busy"

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "courses", boom)
    with TestClient(create_app(), base_url="http://127.0.0.1", raise_server_exceptions=False) as c:
        r = c.get("/api/courses")
    assert r.status_code == 500 and r.json() == {"error": "internal", "message": "boom", "details": []}


def test_cross_origin_writes_and_foreign_hosts_are_refused(client):
    body = {"code": "X1", "name": "x"}
    r = client.post("/api/courses", json=body, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert client.post("/api/courses", json=body, headers={"Origin": "http://127.0.0.1"}).status_code == 201
    assert client.get("/api/courses", headers={"Origin": "http://evil.example"}).status_code == 200  # reads are safe
    assert client.get("/api/courses", headers={"Host": "evil.example"}).status_code == 400


def test_web_folder_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200 and "AutoGrade-RDF" in r.text
    assert client.get("/api/nope").status_code == 404


def test_startup_creates_an_empty_database(fresh_db):
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        assert c.get("/api/courses").json() == []


def test_serve_binds_localhost_on_an_empty_database(fresh_db, monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    cli.main(["serve", "--port", "8123"])
    assert calls == [{"host": "127.0.0.1", "port": 8123}]


def test_pages_get_a_content_security_policy(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in csp and "'wasm-unsafe-eval'" in csp
    assert "content-security-policy" not in client.get("/api/courses").headers
    assert "content-security-policy" not in client.get("/docs").headers
