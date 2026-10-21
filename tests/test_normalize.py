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
