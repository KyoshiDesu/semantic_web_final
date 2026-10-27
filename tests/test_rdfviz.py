"""Knowledge Graph page helpers: dataset-wide presets and the generic RDF graph view."""
import pytest
from rdflib import Graph, Literal

from autograde import explorer, io, kg, pipeline, rdfviz
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


def test_swrl_rule_labels():
    eq = {"menyerap": {"menyerap", "menggunakan"}, "menggunakan": {"menyerap", "menggunakan"}}
    inc = {frozenset(("menghasilkan", "mengonsumsi"))}
    assert rdfviz.swrl_rule("menghasilkan", "mengonsumsi", False, eq, inc) == 1
    assert rdfviz.swrl_rule("menghasilkan", "menghasilkan", True, eq, inc) == 2
    assert rdfviz.swrl_rule("menyerap", "menggunakan", True, eq, inc) == 3
    assert rdfviz.swrl_rule("menyerap", "menggunakan", False, eq, inc) is None


@pytest.mark.parametrize("answer_id, triple, ref, rule", [("Q1_A08", "Q1_A08_t4", "Q1_R2", 1),
                                                          ("Q1_S03", "Q1_S03_t1", "Q1_R5", 2)])
def test_pellet_before_after(answer_id, triple, ref, rule):
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text[answer_id]
    pipeline.run_answer(ctx, answer_id, text, "gold", pipeline.ui_run(), use_llm_feedback=False)
    g = kg.get_graph(kg.answer_graph_name("ui", answer_id, "answer"), kg.gold_graph_name("Q1"))
    _, eq, inc = io.ontology_relations()
    before, after = rdfviz.pellet_dots(g, eq, inc)
    assert "alignedSubject" in before and "contradicts" not in before
    assert f'"{triple}" -> "{ref}" [label="ag:contradicts\\n(Aturan {rule})"' in after
