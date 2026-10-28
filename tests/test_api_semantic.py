"""The Semantic Web views: ontology, named graphs, SPARQL, the gold key and the OWL export."""
from rdflib import Graph

from autograde import db, pipeline, rdfviz

GOLD = "urn:ag:gold:Q1"


def test_ontology(client):
    o = client.get("/api/ontology").json()
    assert o["graph"] == "urn:ag:ontology" and o["counts"]["swrl_rules"] == len(o["rules"]) > 0
    assert "digraph" in o["classes_dot"] and o["relations_dot"].startswith("graph {")  # relations are undirected
    assert o["owl"].startswith("<?xml")
    assert o["properties"]["columns"] and o["rules"][0]["title"] and "->" in o["rules"][0]["rule"]
    ids = {p["id"] for p in client.get("/api/ontology?lang=en").json()["predicates"]}
    assert "is_a" in ids and "menggunakan" not in ids


def test_named_graphs(client):
    names = [g["name"] for g in client.get("/api/graphs").json()]
    assert "urn:ag:ontology" in names and GOLD in names
    r = client.get("/api/graphs/turtle", params={"name": GOLD})
    assert r.status_code == 200 and "ReferenceTriple" in r.text and 'filename="gold_Q1.ttl"' in r.headers["content-disposition"]
    view = client.get("/api/graphs/view", params={"name": GOLD}).json()
    assert view["graph"]["nodes"] and "triple" in view["edge_types"]
    assert client.get("/api/graphs/turtle", params={"name": "urn:ag:nope"}).status_code == 404


def test_sparql(client):
    count = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    r = client.post("/api/sparql", json={"query": count}).json()
    assert r["kind"] == "table" and r["columns"] == ["n"] and int(r["rows"][0][0]) > 0
    q = rdfviz.PREFIXES + "SELECT ?r WHERE { ?r a ag:ReferenceTriple } ORDER BY ?r"
    r = client.post("/api/sparql", json={"query": q, "graphs": [GOLD]}).json()
    assert [row[0] for row in r["rows"]] == [f"key:Q1_R{i}" for i in range(1, 6)]
    r = client.post("/api/sparql", json={"query": "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <urn:ag:gold:Q1> { ?s ?p ?o } }"})
    assert r.json()["kind"] == "turtle" and len(Graph().parse(data=r.json()["turtle"], format="turtle")) > 0
    r = client.post("/api/sparql", json={"query": "SELEKT ?x WHERE {"})
    assert r.status_code == 422 and r.json()["message"].startswith("query failed")
    r = client.post("/api/sparql", json={"query": "SELECT * WHERE { SERVICE <http://x> { ?s ?p ?o } }"})
    assert r.status_code == 422
    assert client.post("/api/sparql", json={"query": count, "graphs": ["urn:ag:nope"]}).status_code == 422


def test_sparql_templates(client):
    assert client.get("/api/sparql/templates?scope=kg").json() == rdfviz.KG_QUERIES
    assert set(client.get("/api/sparql/templates?scope=run").json()) == {*rdfviz.RUN_QUERIES, *rdfviz.ANSWER_QUERIES}


def test_gold_key(client):
    g = client.get("/api/questions/Q1/gold").json()
    assert g["graph"] == GOLD and [t["id"] for t in g["triples"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert {c["id"]: c["weight"] for c in g["criteria"]} == {"K1_Bahan": 4, "K2_Produk": 4, "K3_Energi": 2}
    assert "digraph" in g["concept_dot"] and "ReferenceTriple" in g["turtle"]
    assert client.get("/api/questions/Q404/gold").status_code == 404


def test_owl_export(client):
    ctx = pipeline.Context.load("Q1")
    text = db.answers(include_synthetic=True).set_index("answer_id").text["Q1_A07"]
    pipeline.run_answer(ctx, "Q1_A07", text, "gold", pipeline.ui_run(), use_llm_feedback=False)
    r = client.get("/api/export/owl", params={"run": "ui", "answer": "Q1_A07"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/rdf+xml")
    assert 'filename="autograde-ui-Q1_A07.owl"' in r.headers["content-disposition"]
    assert len(Graph().parse(data=r.content, format="xml")) > 0
    assert client.get("/api/export/owl", params={"run": "nope"}).status_code == 404
    assert client.get("/api/export/owl", params={"run": "ui", "answer": "Q1_A01"}).status_code == 404


def test_template_titles_follow_the_language(client):
    en = client.get("/api/sparql/templates", params={"scope": "kg", "lang": "en"}).json()
    assert list(en)[0] == "Triples per named graph" and list(en.values()) == list(rdfviz.KG_QUERIES.values())
