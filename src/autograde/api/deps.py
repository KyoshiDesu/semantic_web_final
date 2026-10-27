"""Lookups that turn an unknown id into a 404, and the upload size limit."""
from fastapi import HTTPException

from autograde import db

MAX_UPLOAD = 10 * 1024 * 1024


def course_or_404(course_id):
    c = db.course(course_id)
    if c is None:
        raise HTTPException(404, f"unknown course {course_id}")
    return c


def assessment_or_404(assessment_id):
    a = db.assessment(assessment_id)
    if a is None:
        raise HTTPException(404, f"unknown assessment {assessment_id}")
    return a


def question_or_404(qid):
    try:
        return db.question(qid)
    except KeyError:
        raise HTTPException(404, f"unknown question {qid}") from None


def run_or_404(run_id):
    r = db.run(run_id)
    if r is None:
        raise HTTPException(404, f"unknown run {run_id}")
    return r


def result_or_404(run_id, answer_id):
    r = db.result(run_id, answer_id)
    if r is None:
        raise HTTPException(404, f"{answer_id} is not graded in run {run_id}")
    return r


def read_upload(file):
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{file.filename} is larger than 10 MB")
    return data


def is_stale(result):
    """Graded before its question's key was last edited (grades.status_table's 'usang')."""
    updated = db.question_updated([result["question_id"]]).get(result["question_id"])
    return bool(updated and result["graded"] and result["graded"] < updated)
