"""The Semantic Web views: ontology, named graphs, SPARQL, the gold key, graded answers and the OWL export
(Ontologi, Soal & Kunci, Nilai Jawaban, Konsol SPARQL, Penjelajah Graf, Graf Pengetahuan)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from rdflib import OWL, RDF, Namespace

from autograde import gold, importer, io, kg, owl_export, rdfviz
from autograde.api import deps
from autograde.api.schemas import SparqlIn, table

router = APIRouter(tags=["semantic"])
SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
TEMPLATES = {"answer": rdfviz.ANSWER_QUERIES, "run": {**rdfviz.RUN_QUERIES, **rdfviz.ANSWER_QUERIES},
             "kg": rdfviz.KG_QUERIES}


def _graph_name(name):
    if name not in {g["name"] for g in kg.graphs()}:
        raise HTTPException(404, f"no named graph {name}")
    return name


def _rules():
    rules = []
    for block in (io.ROOT / "ontology" / "rules.swrl.txt").read_text(encoding="utf-8").strip().split("\n\n"):
        title, rule = block.split("\n", 1)
        rules.append({"title": title.lstrip("# "), "rule": rule})
    return rules


@router.get("/ontology")
def ontology(lang: Literal["all", "id", "en"] = "all"):
    g = io.ontology_graph()
    preds = io.load_predicates()["predicates"]
    only = None if lang == "all" else {p["id"] for p in preds if p.get("lang") == lang}
    return {"graph": kg.ONTOLOGY,
            "counts": {"classes": sum(1 for x in g.subjects(RDF.type, OWL.Class) if str(x).startswith(str(io.AG))),
                       "object_properties": len(set(g.subjects(RDF.type, OWL.ObjectProperty))),
                       "data_properties": len(set(g.subjects(RDF.type, OWL.DatatypeProperty))),
                       "relations": len(set(g.subjects(RDF.type, io.AG.Relation))),
                       "swrl_rules": len(set(g.subjects(RDF.type, SWRL.Imp)))},
            "classes_dot": rdfviz.ontology_classes_dot(g),
            "properties": table(rdfviz.properties_table(g)),
            "relations_dot": rdfviz.relations_dot(g, only),
            "predicates": [p for p in preds if only is None or p["id"] in only],
            "rules": _rules(),
            "owl": io.ontology_path().read_text(encoding="utf-8")}


@router.get("/graphs")
def graphs():
    return kg.graphs()


@router.get("/graphs/turtle")
def graph_turtle(name: str):
    ttl = kg.get_graph(_graph_name(name)).serialize(format="turtle")
    return Response(ttl, media_type="text/turtle; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{rdfviz.turtle_file_name(name)}"'})


@router.get("/graphs/view")
def graph_view(name: str):
    return {"graph": rdfviz.vis_graph(kg.get_graph(_graph_name(name))), "node_types": rdfviz.VIS_NODE_TYPES,
            "edge_types": rdfviz.VIS_EDGE_TYPES}


@router.post("/sparql")
def sparql(body: SparqlIn):
    """Read-only: SERVICE is refused and updates don't parse."""
    if body.graphs:
        known = {g["name"] for g in kg.graphs()}
        missing = [n for n in body.graphs if n not in known]
        if missing:
            raise HTTPException(422, [f"no named graph {n}" for n in missing])
    try:
        if body.graphs:
            result = rdfviz.run_query(rdfviz.merged_graph(body.graphs), body.query)
        else:
            result = kg.query(body.query)
            if not isinstance(result, str):
                result = result.map(lambda v: rdfviz.short(v) if isinstance(v, str) else v)
    except kg.KGBusyError:
        raise
    except Exception as e:  # a syntax or evaluation error is the user's query, not the server's fault
        raise HTTPException(422, f"query failed: {e}") from None
    if isinstance(result, str):
        return {"kind": "turtle", "turtle": result}
    return {"kind": "table", **table(result)}


@router.get("/sparql/templates")
def templates(scope: Literal["answer", "run", "kg"] = "kg"):
    return TEMPLATES[scope]


@router.get("/questions/{qid}/gold")
def gold_key(qid: str):
    q = deps.question_or_404(qid)
    gold_raw, rubric, refs = gold.load(qid)
    weights = gold.criterion_weights(refs)
    name = kg.gold_graph_name(qid)
    return {"graph": name, "prompt": q["prompt"], "reference_answer": q["reference_answer"],
            "language": rubric.get("language", "id"), "validated_by": gold_raw.get("validated_by"),
            "drafted_by": gold_raw.get("drafted_by"),
            "criteria": [{**c, "weight": weights.get(c["id"], 0)} for c in rubric["criteria"]],
            "triples": [r.model_dump() for r in refs],
            "concepts": [{"concept": c, "aliases": (v or {}).get("aliases", []), "broader": (v or {}).get("broader") or []}
                         for c, v in gold_raw["concepts"].items()],
            "concept_dot": rdfviz.gold_concept_dot(refs, gold_raw["concepts"]),
            "reified_dot": rdfviz.gold_reified_dot(qid, refs),
            "turtle": kg.get_graph(name).serialize(format="turtle")}


@router.get("/export/owl")
def export_owl(run: str, answer: str | None = None):
    try:
        data = owl_export.rdfxml(run, answer)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    name = f"autograde-{importer.slug(run)}" + (f"-{importer.slug(answer)}" if answer else "") + ".owl"
    return Response(data, media_type="application/rdf+xml",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
