import pytest

from autograde.io import java_exe


def pytest_collection_modifyitems(config, items):
    if java_exe():
        return
    skip = pytest.mark.skip(reason="Java not found (needed for Pellet)")
    for item in items:
        if "pellet" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def imported_db(tmp_path_factory):
    """Every test runs against real SQLite + Oxigraph stores imported from the repo's data/."""
    from autograde import importer
    mp = pytest.MonkeyPatch()
    mp.setenv("AUTOGRADE_DB_DIR", str(tmp_path_factory.mktemp("db")))
    importer.import_files()
    yield
    mp.undo()


from pathlib import Path  # noqa: E402

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


@pytest.fixture
def client(fresh_db, monkeypatch):
    """The API on a fresh import of the demo data, grading offline: stub embeddings, SPARQL reasoner, no API key."""
    from fastapi.testclient import TestClient

    from autograde import importer, llm, pipeline
    from autograde.api import jobs
    from autograde.api.app import create_app
    from test_pipeline import STUB
    importer.import_files()
    orig = pipeline.Context.load.__func__
    monkeypatch.setattr(pipeline.Context, "load",
                        classmethod(lambda cls, q, **k: orig(cls, q, reasoner="sparql", cosine=STUB)))
    monkeypatch.setattr(jobs, "_contexts", {})  # contexts built with the stub must not leak into other tests
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)  # a real key in .env must never reach a test
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with TestClient(create_app(), base_url="http://127.0.0.1") as c:
        yield c
