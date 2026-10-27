"""Grading an assessment: background jobs, the status table, review, corrections and the CSV exports (Penilaian)."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from autograde import db, grades, importer, pipeline
from autograde.api import deps, jobs
from autograde.api.schemas import CorrectionsIn, GradingRequest, ReviewerIn, table

router = APIRouter(tags=["grading"])
EXPORT_NAMES = {"grades": "nilai", "feedback": "umpan_balik"}


def _status(assessment_id):
    deps.assessment_or_404(assessment_id)
    run_id = pipeline.assessment_run(assessment_id)
    return run_id, grades.status_table(assessment_id, run_id)


def _pending(run_id, answer_id):
    """A graded, up-to-date, unreviewed result: the only kind review and corrections accept."""
    r = deps.result_or_404(run_id, answer_id)
    if deps.is_stale(r):
        raise HTTPException(409, f"{answer_id}: its key was edited after grading; grade it again first")
    if r["reviewed"]:
        raise HTTPException(409, f"{answer_id} is already reviewed")
    return r


@router.get("/assessments/{assessment_id}/status")
def status(assessment_id: int):
    run_id, t = _status(assessment_id)
    a = db.assessment(assessment_id)
    return {"run_id": run_id, "assessment": a, "course": db.course(a["course_id"]),
            "job": db.latest_job(assessment_id),
            "counts": {s: int(n) for s, n in t.status.value_counts().items()},
            "approvable": grades.bulk_approvable(t), "ready": grades.ready(t),
            "synthetic": bool((t.source == "synthetic").any()), **table(t)}


@router.post("/assessments/{assessment_id}/grading", status_code=202)
def start_grading(assessment_id: int, body: GradingRequest):
    deps.assessment_or_404(assessment_id)
    try:
        return jobs.start(assessment_id, body.which, body.llm_feedback)
    except jobs.NothingToGrade as e:
        raise HTTPException(422, str(e)) from None
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e)) from None


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    j = db.job(job_id)
    if j is None:
        raise HTTPException(404, f"unknown job {job_id}")
    return j


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    get_job(job_id)
    try:
        return jobs.cancel(job_id)
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e)) from None


@router.post("/assessments/{assessment_id}/review/bulk")
def bulk_review(assessment_id: int, body: ReviewerIn):
    """Approves every graded answer with no ⚑ entry and no contradiction."""
    run_id, t = _status(assessment_id)
    ids = grades.bulk_approvable(t)
    db.mark_reviewed(run_id, ids, body.by)
    return {"reviewed": ids}


@router.post("/results/{run_id}/{answer_id}/review")
def review(run_id: str, answer_id: str, body: ReviewerIn):
    _pending(run_id, answer_id)
    db.mark_reviewed(run_id, [answer_id], body.by)
    r = db.result(run_id, answer_id)
    return {"answer_id": answer_id, "reviewed": r["reviewed"], "reviewed_by": r["reviewed_by"]}


@router.post("/results/{run_id}/{answer_id}/corrections")
def correct(run_id: str, answer_id: str, body: CorrectionsIn):
    """The lecturer's ledger corrections; the score is recomputed and checked with SPARQL."""
    r = _pending(run_id, answer_id)
    unknown = sorted({c.reference_id for c in body.corrections} - {e["reference_id"] for e in r["ledger"]})
    if unknown:
        raise HTTPException(422, [f"{x} is not in this answer's ledger" for x in unknown])
    db.add_overrides([{"answer_id": answer_id, "reference_id": c.reference_id, "status": c.status, "by": body.by,
                       "date": date.today().isoformat(), "reason": c.reason} for c in body.corrections])
    sc, skipped = pipeline.apply_corrections(run_id, answer_id)
    return {"score": sc.model_dump(), "skipped": skipped}


@router.get("/assessments/{assessment_id}/exports/{kind}.csv")
def export(assessment_id: int, kind: Literal["grades", "feedback"], draft: bool = False):
    """The final files unlock only when every answer is reviewed; drafts are always available."""
    run_id, t = _status(assessment_id)
    if t.empty:
        raise HTTPException(409, "this assessment has no answers")
    if not draft and not grades.ready(t):
        missing = t[t.status != "ditinjau"].status.value_counts()
        raise HTTPException(409, "final export locked: " + ", ".join(f"{n} {s}" for s, n in missing.items()))
    text = grades.grades_csv(t, db.questions(assessment_id), draft) if kind == "grades" \
        else grades.feedback_csv(t, run_id)
    a = db.assessment(assessment_id)
    name = f"{importer.slug(db.course(a['course_id'])['code'] + '_' + a['name'])}_{EXPORT_NAMES[kind]}" \
           f"{'_draf' if draft else ''}.csv"
    return Response(text.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


SEARCH_FILTERS = {"contradiction": lambda row, r: row["contradictions"] > 0,
                  "flagged": lambda row, r: row["status"] == "dinilai" and row["flagged"] > 0,
                  "corrected": lambda row, r: bool(r and r["score_corrected"]),
                  "ungraded": lambda row, r: row["status"] == "belum dinilai"}


def _triple(s):
    return {"s": s["s_text"], "p": s["p"], "o": s["o_text"], "negated": s["negated"]}


def highlight(r):
    """The triple an answer card shows: a contradicting one if any, else the first matched one."""
    if r is None:
        return None
    students = {s["id"]: s for s in r["students"]}
    if r["trace"]["contradictions"]:
        t_id, ref = r["trace"]["contradictions"][0]
        return {**_triple(students[t_id]), "contradicts": f"key:{r['question_id']}_{ref}"}
    matched = next((e["matched_by"] for e in r["ledger"] if e["matched_by"]), None)
    return {**_triple(students[matched]), "contradicts": None} if matched else None


@router.get("/answers")
def search_answers(q: str = "", filter_: Literal["contradiction", "flagged", "corrected", "ungraded"] | None =
                   Query(None, alias="filter"), limit: int = Query(30, ge=1, le=200)):
    """The home page's search over every assessment: each answer with its grading status, score and one triple.
    Every word of q must appear in the answer id, student id or name, answer text, question id or prompt."""
    words, out = q.lower().split(), []
    for course in db.courses():
        for a in db.assessments(course["id"]):
            run_id = pipeline.assessment_run(a["id"])
            data, results = table(grades.status_table(a["id"], run_id)), db.results(run_id)
            texts = db.assessment_answers(a["id"]).set_index("answer_id").text
            prompts = {qid: db.question(qid)["prompt"] for qid in db.questions(a["id"])}
            for row in (dict(zip(data["columns"], values)) for values in data["rows"]):
                r = results.get(row["answer_id"])
                hay = " ".join((row["answer_id"], row["external_id"], row["name"] or "", texts[row["answer_id"]],
                                row["question_id"], prompts[row["question_id"]])).lower()
                if all(w in hay for w in words) and (filter_ is None or SEARCH_FILTERS[filter_](row, r)):
                    out.append({**row, "assessment_id": a["id"], "run_id": run_id, "text": texts[row["answer_id"]],
                                "corrected": bool(r and r["score_corrected"]), "triple": highlight(r)})
                    if len(out) == limit:
                        return out
    return out
