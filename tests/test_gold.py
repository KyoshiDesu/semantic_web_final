import copy

import pytest
from rdflib import RDF, Graph

from autograde import gold, io
from autograde.io import AG

RELS = {"menggunakan", "menyerap", "mengonsumsi", "menghasilkan"}


@pytest.fixture
def q1():
    d = io.question_dir("Q1")
    return io.load_yaml(d / "gold.yaml"), io.load_yaml(d / "rubric.yaml")


def test_valid_gold(q1):
    refs = gold.validate(*q1, RELS)
    assert [r.id for r in refs] == ["R1", "R2", "R3", "R4", "R5"]
    assert refs[1].s == ["Fotosintesis", "Tumbuhan"]


@pytest.mark.parametrize("mutate, msg", [
    (lambda g: g["triples"][0].update(weight=0), "greater than 0"),
    (lambda g: g["triples"][0].update(p="memakan"), "unknown predicate"),
    (lambda g: g["triples"].pop(0), "K3_Energi has no reference triple"),
    (lambda g: g["triples"][0].update(o="Klorofil"), "undeclared concept"),
])
def test_validation_errors(q1, mutate, msg):
    g, rubric = copy.deepcopy(q1[0]), q1[1]
    mutate(g)
    with pytest.raises(gold.GoldError, match=msg):
        gold.validate(g, rubric, RELS)


def test_predicate_vocab_checks():
    good = {"predicates": [{"id": "menggunakan", "aliases": ["memakai"]}, {"id": "other", "aliases": []}]}
    gold.check_predicates(good, RELS)
    with pytest.raises(gold.GoldError, match="missing from the ontology"):
        gold.check_predicates({"predicates": [{"id": "memasak", "aliases": []}]}, RELS)
    with pytest.raises(gold.GoldError, match="also predicate ids"):
        gold.check_predicates({"predicates": [{"id": "menggunakan", "aliases": ["menyerap"]},
                                              {"id": "menyerap", "aliases": []}]}, RELS)


def test_gold_ttl_round_trip(tmp_path, q1):
    refs = gold.validate(*q1, RELS)
    path = tmp_path / "gold.ttl"
    gold.to_graph("Q1", refs, q1[1]).serialize(path, format="turtle")
    g = Graph().parse(path)
    ids = sorted(str(s).split("#")[1] for s in g.subjects(RDF.type, AG.ReferenceTriple))
    assert ids == [f"Q1_{r.id}" for r in refs]
    assert len(list(g.objects(AG.Q1_R2, AG.hasSubject))) == 2
    assert len(g) == len(gold.to_graph("Q1", refs, q1[1]))
