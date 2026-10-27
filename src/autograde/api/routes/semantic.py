"""The Semantic Web views: ontology, named graphs, SPARQL, the gold key, graded answers and the OWL export
(Ontologi, Soal & Kunci, Nilai Jawaban, Konsol SPARQL, Penjelajah Graf, Graf Pengetahuan)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from rdflib import OWL, RDF, Namespace

from autograde import baselines, db, evaluate, explorer, feedback, gold, importer, io, kg, ledger, owl_export, \
    pipeline, rdfviz
from autograde.api import deps, jobs
from autograde.api.schemas import SparqlIn, TryIn, table

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
def templates(scope: Literal["answer", "run", "kg"] = "kg", lang: Literal["id", "en"] = "id"):
    return {rdfviz.TITLES_EN.get(k, k) if lang == "en" else k: v for k, v in TEMPLATES[scope].items()}


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


OLD_KEY = "graded with an older version of the key that this view can't draw; grade it again"


def human_totals(ctx):
    """Lecturer totals (0-100) of the question's answers, shown in the answer list and the explorer."""
    scores = db.human_scores(include_synthetic=True)
    sub = scores[scores.answer_id.isin(list(db.answer_ids([ctx.qid])))]
    if sub.empty:
        return {}
    try:
        return evaluate.human_totals(sub, {ctx.qid: gold.criterion_weights(ctx.refs)},
                                     dict.fromkeys(sub.answer_id.unique(), ctx.qid)).to_dict()
    except ValueError:  # scores for only some criteria: no total
        return {}


def result_view(run_id, answer_id):
    r = deps.result_or_404(run_id, answer_id)
    run = db.run(run_id)
    qid, params = r["question_id"], run["params"]
    gold_name, answer_name, ledger_name = rdfviz.answer_graph_names(qid, run_id, answer_id)
    rows = ledger.recompute_rows(kg.get_graph(ledger_name), kg.get_graph(gold_name), params["lambda"])
    refs = {x.id: x for x in gold.load(qid)[2]}

    def labelled(entries):  # reference None: the triple is no longer in the key
        return entries and [{**e, "reference": feedback.triple_label(refs[e["reference_id"]])
                             if e["reference_id"] in refs else None} for e in entries]

    sc = r["score"]
    return {"run_id": run_id, "answer_id": answer_id, "question_id": qid, "assessment_id": run["assessment_id"],
            "graded": r["graded"],
            "reviewed": r["reviewed"], "reviewed_by": r["reviewed_by"], "stale": deps.is_stale(r),
            "score": sc, "score_corrected": r["score_corrected"],
            "recompute": {"query": ledger.RECOMPUTE_QUERY.strip(), "graphs": [ledger_name, gold_name],
                          "rows": [{"answer": rdfviz.short(x.ans), "raw": float(x.raw.toPython())} for x in rows],
                          "python": sc["score"], "sparql": sc["sparql_score"],
                          "ok": sc["sparql_score"] is not None and abs(sc["score"] - sc["sparql_score"]) < 1e-9},
            "ledger": labelled(r["ledger"]), "ledger_corrected": labelled(r["ledger_corrected"]),
            "feedback": r["feedback"], "sentences": r["sentences"], "students": r["students"],
            "extraction_log": r["extraction_log"], "graphs": [gold_name, answer_name, ledger_name]}


@router.get("/questions/{qid}/answers")
def question_answers(qid: str):
    deps.question_or_404(qid)
    df = db.answers(include_synthetic=True)
    df = df[df.question_id == qid].drop(columns=["question_id"])
    df["human"] = df.answer_id.map(human_totals(jobs.context(qid)))
    return table(df)


@router.post("/questions/{qid}/try")
def try_answer(qid: str, body: TryIn):
    """Grades one stored or pasted answer now, in the app's UI run (the Nilai demo)."""
    deps.question_or_404(qid)
    ctx = jobs.context(qid)
    if body.answer_id:
        answers = db.answers(include_synthetic=True).set_index("answer_id")
        if body.answer_id not in answers.index or answers.question_id[body.answer_id] != qid:
            raise HTTPException(422, f"{body.answer_id} is not an answer to {qid}")
        answer_id, text = body.answer_id, answers.text[body.answer_id]
    else:
        answer_id, text = f"{qid}_UI", body.text
    if body.mode == "gold" and db.annotation(answer_id) is None:
        raise HTTPException(422, f"{answer_id} has no triple annotation; use mode llm")
    pipeline.run_answer(ctx, answer_id, text, body.mode, pipeline.ui_run(), body.llm_feedback)
    return {**result_view(pipeline.UI_RUN, answer_id),
            "baseline_b1": float(baselines.b1_keyword(text, ctx.refs, ctx.gold_raw["concepts"]))}


@router.get("/results/{run_id}/{answer_id}")
def get_result(run_id: str, answer_id: str):
    return result_view(run_id, answer_id)


@router.get("/results/{run_id}/{answer_id}/views/{view}")
def result_views(run_id: str, answer_id: str, view: Literal["graph", "alignment", "reasoning"],
                 lang: Literal["id", "en"] = "id"):
    r = deps.result_or_404(run_id, answer_id)
    qid, params = r["question_id"], db.run(run_id)["params"]
    ctx, a = jobs.context(qid), explorer.load_answer(run_id, answer_id)
    trace = {"sigmas": a["sigmas"], "aligned": sorted(a["aligned"]), "contradictions": sorted(a["contradictions"])}
    try:  # a KeyError here means the key gained a reference triple this answer was never matched against
        if view == "graph":
            return {"graph": explorer.build(ctx, [a], params, human_totals(ctx), lang=lang),
                    "node_types": explorer.NODE_TYPES, "edge_types": explorer.EDGE_TYPES}
        if view == "alignment":
            return {"dot": rdfviz.alignment_dot(ctx.refs, a["students"], a["entries"], trace),
                    "graph": kg.answer_graph_name(run_id, answer_id, "answer")}
        sigma = rdfviz.sigma_table(ctx.refs, a["students"], a["sigmas"]).reset_index(names="triple") \
            if a["students"] else None
    except KeyError:
        raise HTTPException(409, f"{answer_id}: {OLD_KEY}") from None
    pellet = None
    if a["aligned"]:
        _, eq, inc = io.ontology_relations()
        g = kg.get_graph(kg.answer_graph_name(run_id, answer_id, "answer"), kg.gold_graph_name(qid))
        before, after = rdfviz.pellet_dots(g, eq, inc)
        pellet = {"before": before, "after": after}
    return {"params": params, "students": [t.model_dump() for t in a["students"]],
            "sigma": None if sigma is None else table(sigma), "aligned": trace["aligned"],
            "contradictions": trace["contradictions"], "pellet": pellet, "extraction_log": r["extraction_log"]}


@router.get("/questions/{qid}/explorer")
def explorer_view(qid: str, run: str | None = None, answers: str = "", lang: Literal["id", "en"] = "id"):
    """The question's knowledge graph; with a run, plus the chosen answers (default: its first 12)."""
    deps.question_or_404(qid)
    ctx = jobs.context(qid)
    sources = [{"run_id": r["run_id"], "answers": ids} for r in pipeline.completed_runs()
               if (ids := db.result_ids(r["run_id"], qid))]
    if ui := db.result_ids(pipeline.UI_RUN, qid):
        sources.append({"run_id": pipeline.UI_RUN, "answers": ui})
    chosen, params = [], ctx.params
    if run:
        params = deps.run_or_404(run)["params"]
        graded = db.result_ids(run, qid)
        ids = [x for x in answers.split(",") if x] or graded[:12]
        missing = sorted(set(ids) - set(graded))
        if missing:
            raise HTTPException(404, f"not graded in run {run}: {', '.join(missing)}")
        chosen = [explorer.load_answer(run, x) for x in ids]
    try:
        graph = explorer.build(ctx, chosen, params, human_totals(ctx), lang=lang)
    except KeyError:
        raise HTTPException(409, f"an answer was {OLD_KEY}") from None
    return {"sources": sources, "graph": graph, "node_types": explorer.NODE_TYPES, "edge_types": explorer.EDGE_TYPES}
