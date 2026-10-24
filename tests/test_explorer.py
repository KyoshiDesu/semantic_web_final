"""Semantic Explorer graph: built from a graded answer as stored in the database; the page escapes student text."""
import json

import explorer
from autograde import io, pipeline
from test_pipeline import STUB


def graded(qid, answer_id, text):
    ctx = pipeline.Context.load(qid, reasoner="sparql", cosine=STUB)
    run_id = pipeline.ui_run()
    pipeline.run_answer(ctx, answer_id, text, "gold", run_id, use_llm_feedback=False)
    return ctx, explorer.load_answer(run_id, answer_id)


def test_contradiction_edge_and_reasoning():
    text = io.load_answers(include_synthetic=True).set_index("answer_id").text["Q1_A08"]
    ctx, a = graded("Q1", "Q1_A08", text)
    g = explorer.build(ctx, [a], ctx.params)
    kinds = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("ans:Q1_A08_t4", "key:Q1_R2", "inferred") in kinds  # menghasilkan CO2 vs the key's mengonsumsi CO2
    assert ("ag:menghasilkan", "ag:mengonsumsi", "ontology") in kinds
    reasoning = g["details"]["ans:Q1_A08_t4"]["sections"][1]["items"][0]
    assert "Aturan 1" in reasoning and "incompatibleWith" in reasoning
    assert {e["from"] for e in g["edges"]} | {e["to"] for e in g["edges"]} <= {n["id"] for n in g["nodes"]}


def test_match_edges_for_worked_example():
    text = io.load_yaml(io.ROOT / "tests" / "fixtures" / "worked_example.yaml")["text"]
    ctx, a = graded("Q1", "Q1_A07", text)
    g = explorer.build(ctx, [a], ctx.params)
    matches = {(e["from"], e["to"]) for e in g["edges"] if e["kind"] == "match"}
    assert ("ans:Q1_A07_t1", "key:Q1_R1") in matches  # menyerap ≡ menggunakan
    assert ("ans:Q1_A07_t2", "key:Q1_R4") in matches  # "makanan" is broader than Glukosa: partial
    assert ("key:Glukosa", "key:Makanan", "hierarchy") in {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert "lebih umum dari Glukosa" in " ".join(g["details"]["ans:Q1_A07_t2"]["sections"][1]["items"])
    assert "equivalentPredicate" in json.dumps(g["edges"])


def test_page_cannot_be_broken_by_student_text():
    ctx, a = graded("Q1", "Q1_A07", "Tumbuhan menyerap sinar matahari.")
    g = explorer.build(ctx, [a], ctx.params)
    g["details"]["ans:Q1_A07"]["sections"][0]["items"] = ["</script><script>alert(1)</script>"]
    page = explorer.html(g)
    data = page.split("const D = ", 1)[1]
    assert "</script><script>alert" not in data and "<\\/script><script>alert(1)" in data
