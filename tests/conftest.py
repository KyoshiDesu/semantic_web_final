from pathlib import Path

import pytest

from autograde.io import java_exe


def _chromium_installed():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # playwright missing or its driver broken: the browser tests are skipped, not failed
        return False


def pytest_collection_modifyitems(config, items):
    skips = []
    if not java_exe():
        skips.append(("pellet", "Java not found (needed for Pellet)"))
    if any(item.get_closest_marker("browser") for item in items) and not _chromium_installed():
        skips.append(("browser", "Chromium not installed (run `playwright install chromium`)"))
    for marker, reason in skips:
        for item in items:
            if item.get_closest_marker(marker):
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session", autouse=True)
def imported_db(tmp_path_factory):
    """Every test runs against real SQLite + Oxigraph stores imported from the repo's data/."""
    from autograde import importer
    mp = pytest.MonkeyPatch()
    mp.setenv("AUTOGRADE_DB_DIR", str(tmp_path_factory.mktemp("db")))
    importer.import_files()
    yield
    mp.undo()


from autograde import gold, io as agio  # noqa: E402
from autograde.match import Relations  # noqa: E402
from autograde.models import StudentTriple  # noqa: E402
from autograde.normalize import ConceptIndex, fill_concepts, make_sim  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "worked_example.yaml"


def _students(answer_id, raws, index):
    triples = [StudentTriple(id=f"{answer_id}_t{i}", answer_id=answer_id, s_text=r["s"], p=r["p"], o_text=r["o"],
                             negated=r.get("negated", False), sentence_ids=[f"{answer_id}_s{n}" for n in r["sentences"]])
               for i, r in enumerate(raws, 1)]
    return fill_concepts(triples, index)


@pytest.fixture(scope="session")
def worked(imported_db):
    """Deck example A07 with the stubbed embedding, plus its contradiction variant."""
    fx = agio.load_yaml(FIXTURE)
    gold_raw, rubric, refs = gold.load("Q1")
    index = ConceptIndex(gold_raw["concepts"])
    table = {frozenset((a, b)): v for a, b, v in fx["stub_cosine"]}
    sim = make_sim(lambda a, b: 1.0 if a == b else table.get(frozenset((a, b)), 0.0), gold.ancestors(gold_raw["concepts"]))
    variant_raws = fx["triples"][:3] + [fx["contradiction_variant"]["replace_triple_4"]]
    return {"fx": fx, "refs": refs, "rubric": rubric, "sim": sim, "rel": Relations.from_ontology(),
            "params": fx["params"], "students": _students(fx["answer_id"], fx["triples"], index),
            "variant": _students(fx["answer_id"], variant_raws, index), "index": index}


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """An empty, separate database directory for tests that build their own data."""
    monkeypatch.setenv("AUTOGRADE_DB_DIR", str(tmp_path / "db"))
    return tmp_path / "db"


def offline(mp):
    """Grade without network or keys: stub embeddings, SPARQL reasoner, no API key, no cached contexts."""
    from autograde import llm, pipeline
    from autograde.api import jobs
    from test_pipeline import STUB
    orig = pipeline.Context.load.__func__
    mp.setattr(pipeline.Context, "load", classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    mp.setattr(jobs, "_contexts", {})  # contexts built with the stub must not leak into other tests
    mp.setattr(llm, "load_dotenv", lambda *a, **k: None)  # a real key in .env must never reach a test
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    mp.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


@pytest.fixture
def client(fresh_db, monkeypatch):
    """The API on a fresh import of the demo data, grading offline."""
    from fastapi.testclient import TestClient

    from autograde import importer
    from autograde.api.app import create_app
    importer.import_files()
    offline(monkeypatch)
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        yield c


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """The web app on a free port in a thread, on a fresh import of the demo data, grading offline. One per module."""
    import socket
    import threading
    import time

    import uvicorn

    from autograde import importer
    from autograde.api.app import create_app
    mp = pytest.MonkeyPatch()
    mp.setenv("AUTOGRADE_DB_DIR", str(tmp_path_factory.mktemp("web-db")))
    importer.import_files()
    offline(mp)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)
    mp.undo()


@pytest.fixture
def errors(page):
    """Console errors, page errors, failed requests and missing translations seen by the page."""
    seen = []
    page.on("console", lambda m: seen.append(f"{m.type}: {m.text}")
            if m.type == "error" or (m.type == "warning" and m.text.startswith("i18n")) else None)
    page.on("pageerror", lambda e: seen.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: seen.append(f"requestfailed: {r.url} {r.failure}"))
    return seen
