"""Orchestrates one answer, one question, or a whole split; stores results in the database and the knowledge graph."""
from dataclasses import dataclass
from datetime import datetime

from autograde import db, extract, feedback, gold, io, kg, ledger, reason, segment
from autograde.match import Relations, match
from autograde.models import LedgerEntry
from autograde.normalize import ConceptIndex, Embedder, fill_concepts, make_sim
from autograde.score import score


class ParityError(RuntimeError):
    pass


@dataclass
class Context:
    qid: str
    gold_raw: dict
    rubric: dict
    refs: list
    index: ConceptIndex
    sim: object
    rel: Relations
    params: dict
    reasoner: str
    broader_similarity: float

    @classmethod
    def load(cls, qid, params=None, reasoner=None, cosine=None):
        gold_raw, rubric, refs = gold.load(qid)
        if not kg.has_graph(kg.gold_graph_name(qid)):
            gold.store_graph(qid)
        cfg = io.load_config()
        broader = float(cfg.get("broader_similarity", 0.70))
        sim = make_sim(cosine or Embedder().cosine, gold.ancestors(gold_raw["concepts"]), broader)
        return cls(qid, gold_raw, rubric, refs, ConceptIndex(gold_raw["concepts"]), sim, Relations.from_ontology(),
                   params or io.load_params(), reasoner or cfg["reasoner"], broader)


def grade(ctx, answer_id, students, params=None):
    """Matching, reasoning, ledger and score for already-extracted triples (no files written).

    Returns (students, entries, score, trace); trace holds σ for every pair, the aligned pairs given to the
    reasoner, and the contradictions it inferred."""
    params = params or ctx.params
    if not params["tau_l"] <= ctx.broader_similarity < params["tau_h"]:
        raise ValueError(f"broader_similarity {ctx.broader_similarity} must lie in the partial band "
                         f"[{params['tau_l']}, {params['tau_h']}) so a broader concept earns partial credit")
    students = fill_concepts(students, ctx.index)
    results, sigmas, aligned = match(ctx.refs, students, params, ctx.sim, ctx.rel)
    contra = reason.contradictions(ctx.qid, ctx.refs, students, aligned, ctx.reasoner)
    entries = ledger.build(answer_id, ctx.refs, results, sigmas, contra, students, params)
    trace = {"sigmas": sigmas, "aligned": aligned, "contradictions": sorted(contra)}
    return students, entries, score(answer_id, entries, params), trace


def extract_triples(ctx, answer_id, sentences, mode):
    if mode == "llm":
        return extract.extract_llm(answer_id, sentences, language=ctx.rubric.get("language", "id"))
    if mode == "gold":
        return extract.extract_gold(answer_id), []
    raise ValueError(f"unknown mode {mode!r}")


UI_RUN = "ui"


def ui_run():
    """The app's run for single answers graded on the Grade page: never finished, never evaluated."""
    db.create_run(UI_RUN, "ui", "all", "all", io.load_params(), io.frozen_path().exists(),
                  io.load_config()["reasoner"], True)
    return UI_RUN


def run_answer(ctx, answer_id, text, mode, run_id, use_llm_feedback=True):
    sentences = segment.split(answer_id, text)
    students, log = extract_triples(ctx, answer_id, sentences, mode)
    students, entries, sc, trace = grade(ctx, answer_id, students)
    answer_name = kg.answer_graph_name(run_id, answer_id, "answer")
    ledger_name = kg.answer_graph_name(run_id, answer_id, "ledger")
    kg.put_graph(answer_name, ledger.answer_graph(answer_id, students, sentences, ctx.qid, trace))
    kg.put_graph(ledger_name, ledger.to_graph(ctx.qid, entries))
    # the audit reads the graphs back from the store: it checks what was persisted, not what is in memory
    sc.sparql_score = ledger.recompute_sparql(kg.get_graph(ledger_name), kg.get_graph(kg.gold_graph_name(ctx.qid)),
                                              ctx.params["lambda"])
    if abs(sc.score - sc.sparql_score) >= 1e-9:
        raise ParityError(f"{answer_id}: Python score {sc.score} != SPARQL score {sc.sparql_score}")
    fb = feedback.generate(answer_id, entries, ctx.refs, ctx.rubric, sentences, sc.score, use_llm=use_llm_feedback)
    res = {"sentences": sentences, "students": students, "entries": entries, "score": sc, "feedback": fb,
           "log": log, "trace": trace, "run_id": run_id}
    db.save_result(run_id, ctx.qid, answer_id, res)  # last: the row marks the answer as done
    return res


def completed_runs():
    """Finished runs, newest first (dicts from the run table)."""
    return db.runs(finished_only=True)


def run_split(question, mode, split, include_synthetic=False, use_llm_feedback=True, answer_ids=None, run_id=None):
    """Grade a selection of answers. Re-running the same run_id resumes it: graded answers are skipped."""
    answers = io.load_answers(include_synthetic)
    if question != "all":
        answers = answers[answers.question_id == question]
    if split != "all":
        answers = answers[answers.split == split]
    if answer_ids:
        answers = answers[answers.answer_id.isin(answer_ids)]
    if answers.empty:
        raise ValueError("no answers selected (import real answers with `db import`; use --synthetic for demo data)")
    run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}_{mode}_{split}"
    db.create_run(run_id, mode, split, question, io.load_params(), io.frozen_path().exists(),
                  io.load_config()["reasoner"], include_synthetic)
    done, contexts = set(db.result_ids(run_id)), {}
    for a in answers.itertuples():
        if a.answer_id in done:
            print(f"{a.answer_id}: already graded, skipped")
            continue
        if a.question_id not in contexts:
            contexts[a.question_id] = Context.load(a.question_id)
        ctx = contexts[a.question_id]
        res = run_answer(ctx, a.answer_id, a.text, mode, run_id, use_llm_feedback)
        print(f"{a.answer_id}: {res['score'].score:.1f}")
    db.finish_run(run_id)
    return run_id


def apply_corrections(run_id, answer_id):
    """The lecturer's overrides for this answer applied to its graded ledger: the ledger_corrected graph and the
    corrected score (SPARQL parity checked). Overrides for reference triples that are no longer in the ledger (the key
    changed) are skipped. Returns (corrected ScoreResult or None when no override applies, skipped overrides)."""
    res = db.result(run_id, answer_id)
    if res is None:
        raise KeyError(f"{answer_id} is not graded in run {run_id}")
    params, qid = db.run(run_id)["params"], res["question_id"]
    entries = [LedgerEntry(**e) for e in res["ledger"]]
    refs = {e.reference_id for e in entries}
    overrides = db.overrides(answer_id)
    use = [o for o in overrides if o["reference_id"] in refs]
    skipped = [o for o in overrides if o["reference_id"] not in refs]
    if not use:
        return None, skipped
    fixed = ledger.apply_overrides(entries, use, params)
    name = kg.answer_graph_name(run_id, answer_id, "ledger_corrected")
    kg.put_graph(name, ledger.to_graph(qid, fixed))
    sc = score(answer_id, fixed, params)
    sc.sparql_score = ledger.recompute_sparql(kg.get_graph(name), kg.get_graph(kg.gold_graph_name(qid)),
                                              params["lambda"])
    if abs(sc.score - sc.sparql_score) >= 1e-9:
        raise ParityError(f"{answer_id}: corrected score parity failed")
    db.save_corrected(run_id, answer_id, fixed, sc)
    return sc, skipped


def assessment_run(assessment_id):
    """The one grading run of an assessment, created on first use. Mode auto: see grade_assessment_answer."""
    run_id = f"assessment-{assessment_id}"
    db.create_run(run_id, "auto", "all", "all", io.load_params(), io.frozen_path().exists(),
                  io.load_config()["reasoner"], True, assessment_id)
    return run_id


def grade_assessment_answer(run_id, answer, contexts, use_llm_feedback=False):
    """One row of db.assessment_answers: gold extraction when hand-annotated, else LLM. The lecturer's earlier
    corrections for this answer are re-applied to the new ledger."""
    if answer.question_id not in contexts:
        contexts[answer.question_id] = Context.load(answer.question_id)
    res = run_answer(contexts[answer.question_id], answer.answer_id, answer.text,
                     "gold" if answer.annotated else "llm", run_id, use_llm_feedback)
    apply_corrections(run_id, answer.answer_id)
    return res
