"""Oxigraph store: named-graph round trip, read-only SPARQL, ontology sync, and the process lock."""
import pyoxigraph
import pytest
from rdflib import RDFS, XSD, Graph, Literal
from rdflib.compare import isomorphic

from autograde import db, io, kg
from autograde.io import AG, ANS, KEY


@pytest.fixture
def store(fresh_db):
    db.connect(create=True).close()


def test_put_get_replace_and_list(store):
    name = kg.answer_graph_name("r1", "Q1_A07", "ledger")
    g = Graph()
    g.add((ANS.e1, AG.credit, Literal("0.5", datatype=XSD.decimal)))
    g.add((ANS.e1, RDFS.label, Literal("é \"kutip\"", lang="id")))
    kg.put_graph(name, g)
    assert isomorphic(kg.get_graph(name), g)
    g2 = Graph()
    g2.add((ANS.e2, AG.credit, Literal("0.5", datatype=XSD.decimal)))
    kg.put_graph(name, g2)  # replaces, never appends
    assert len(kg.get_graph(name)) == 1 and len(kg.get_graph(name, "urn:ag:gold:none")) == 1
    assert kg.has_graph(name) and not kg.has_graph("urn:ag:gold:none")
    assert kg.graphs() == [{"name": name, "kind": "ledger", "question": None, "run": "r1", "answer": "Q1_A07",
                            "triples": 1}]
    with pytest.raises(ValueError, match="bogus"):
        kg.answer_graph_name("r", "a", "bogus")


def test_parse_name():
    assert kg.parse_name("urn:ag:ontology")["kind"] == "ontology"
    assert kg.parse_name(kg.gold_graph_name("Q1")) == {"name": "urn:ag:gold:Q1", "kind": "gold", "question": "Q1",
                                                       "run": None, "answer": None}
    assert kg.parse_name(kg.answer_graph_name("20261024-1_gold_all", "Q1_A07", "ledger_corrected"))["kind"] == \
        "ledger_corrected"


def test_query_select_ask_construct_and_refusals(store):
    g = Graph()
    g.add((KEY.A, AG.weight, Literal("x")))
    kg.put_graph("urn:ag:gold:T", g)
    df = kg.query(io.SPARQL_PREFIXES + "SELECT ?g ?o WHERE { GRAPH ?g { key:A ?p ?o } }")
    assert df.to_dict("records") == [{"g": "urn:ag:gold:T", "o": "x"}]
    assert bool(kg.query("ASK { ?s ?p ?o }")["ASK"][0])
    assert "key:A" in kg.query(io.SPARQL_PREFIXES + "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    with pytest.raises(ValueError, match="SERVICE"):
        kg.query("SELECT * WHERE { SERVICE <http://example.org/sparql> { ?s ?p ?o } }")
    with pytest.raises(SyntaxError):
        kg.query("INSERT DATA { <http://a> <http://b> <http://c> }")


def test_sync_ontology_only_on_change(store):
    assert kg.sync_ontology() is True
    assert kg.sync_ontology() is False
    assert len(kg.get_graph(kg.ONTOLOGY)) > 100
    db.set_meta("ontology_sha256", "stale")
    assert kg.sync_ontology() is True


def test_lock_is_reported_after_retry(store, monkeypatch):
    monkeypatch.setattr(kg, "LOCK_WAIT_SECONDS", 0.3)
    holder = pyoxigraph.Store(str(kg.kg_path()))  # another "process" holding the store
    with pytest.raises(kg.KGBusyError, match="in use by another process"):
        kg.put_graph("urn:t", Graph())
    del holder
    kg.put_graph("urn:t", Graph())  # released: works again


def test_calls_do_not_leak_the_store(store):
    g = Graph()
    g.add((KEY.A, AG.weight, Literal("x")))
    kg.put_graph("urn:ag:gold:T", g)
    kg.get_graph("urn:ag:gold:T")
    kg.graphs()
    kg.query("SELECT * WHERE { ?s ?p ?o }")
    kg.query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    pyoxigraph.Store(str(kg.kg_path()))  # raises if any call above kept a reference
