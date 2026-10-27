"""Grading an assessment: background jobs, the status table, review, corrections and the CSV exports (Penilaian)."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Response

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
    return {"run_id": run_id, "counts": {s: int(n) for s, n in t.status.value_counts().items()},
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
