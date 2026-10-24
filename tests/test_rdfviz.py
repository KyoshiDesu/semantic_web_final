"""Knowledge Graph page helpers: dataset-wide presets and the generic RDF graph view."""
import pytest
from rdflib import Graph, Literal

import explorer
import rdfviz
from autograde import io, kg, pipeline
from autograde.io import AG, ANS, KEY
from test_pipeline import STUB


@pytest.fixture(scope="module")
def graded_a07():
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text["Q1_A07"]
    pipeline.run_answer(ctx, "Q1_A07", text, "gold", pipeline.ui_run(), use_llm_feedback=False)


def test_every_kg_preset_runs_and_recompute_matches(graded_a07):
    for name, query in rdfviz.KG_QUERIES.items():
        kg.query(query)  # parses and runs on Oxigraph
    df = kg.query(rdfviz.KG_QUERIES["Hitung ulang skor tiap jawaban (Pers. 6) dari graf tersimpan"])
    row = df[df.ledgerGraph == kg.answer_graph_name("ui", "Q1_A07", "ledger")]
    assert float(row.score.iloc[0]) == pytest.approx(70.0)
    counts = kg.query(rdfviz.KG_QUERIES["Jumlah triple per named graph"]).set_index("graph").triples
    assert int(counts[kg.ONTOLOGY]) > 100 and int(counts[kg.gold_graph_name("Q1")]) > 0


def test_vis_graph_covers_every_triple_and_truncates():
    g = Graph()
    g.add((ANS.t1, AG.hasObject, KEY.CO2))
    g.add((ANS.t1, AG.negated, Literal(False)))
    g.add((KEY.CO2, AG.hasSubject, Literal("x")))
    vis = rdfviz.vis_graph(g)
    assert len(vis["edges"]) == 3 and not vis["truncated"]
    kinds = {n["id"]: n["kind"] for n in vis["nodes"]}
    assert kinds[str(ANS.t1)] == "ans" and kinds[str(KEY.CO2)] == "key"
    assert sum(k == "literal" for k in kinds.values()) == 2  # each literal is its own node
    assert {e["from"] for e in vis["edges"]} | {e["to"] for e in vis["edges"]} <= set(kinds)
    assert rdfviz.vis_graph(g, limit=2)["truncated"]
    page = explorer.html(vis, node_types=rdfviz.VIS_NODE_TYPES, edge_types=rdfviz.VIS_EDGE_TYPES)
    assert "Literal" in page
