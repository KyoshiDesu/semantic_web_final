from autograde.normalize import ConceptIndex, make_sim, norm_text

CONCEPTS = {"CO2": {"aliases": ["karbon dioksida"]}, "Fotosintesis": {"aliases": ["proses fotosintesis"]},
            "Glukosa": {"aliases": ["gula"]}, "Oksigen": None}


def test_norm_text():
    assert norm_text("  CO₂, dan  Air! ") == "co2 dan air"


def test_alias_lookup():
    idx = ConceptIndex(CONCEPTS)
    assert idx.lookup("Karbon Dioksida") == "CO2"
    assert idx.lookup("CO₂") == "CO2"
    assert idx.lookup("proses fotosintesis") == "Fotosintesis"
    assert idx.lookup("oksigen") == "Oksigen"
    assert idx.lookup("makanan") is None


def test_known_different_concepts_never_similar():
    sim = make_sim(lambda a, b: 0.99)  # embedding says "very similar"
    assert sim("Oksigen", "oksigen", "Glukosa", "glukosa") == 0.0
    assert sim("Oksigen", "oksigen", "Oksigen", "O2") == 1.0
    assert sim(None, "makanan", "Glukosa", "glukosa") == 0.99


def test_concept_hierarchy_similarity():
    ancestors = {"Glukosa": {"Makanan"}, "Makanan": set(), "Oksigen": {"Gas"}, "CO2": {"Gas"}, "Gas": set()}
    sim = make_sim(lambda a, b: 0.99, ancestors, broader_similarity=0.70)
    assert sim("Makanan", "makanan", "Glukosa", "glukosa") == 1.0   # student more specific than the key
    assert sim("Glukosa", "glukosa", "Makanan", "makanan") == 0.70  # student more general: partial
    assert sim("Oksigen", "oksigen", "CO2", "co2") == 0.0           # siblings under Gas: different


def test_embedder_is_safe_from_several_threads(tmp_path):
    import json
    import threading

    import numpy as np

    from autograde.normalize import Embedder

    class Model:
        def encode(self, text, normalize_embeddings=True):
            return np.ones(3) / np.sqrt(3)

    e = Embedder("stub-model")
    e.path, e.cache, e._model = tmp_path / "emb.json", {}, Model()
    texts, errors = [f"kata {i}" for i in range(300)], []

    def work(chunk):
        try:
            for t in chunk:
                e.vector(t)
        except Exception as exc:  # collected: an exception in a thread does not fail the test by itself
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(texts[i::4],)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert set(json.loads(e.path.read_text(encoding="utf-8"))) == set(texts)
