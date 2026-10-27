"""LMS CSV imports: preview the columns, then import answers or lecturer scores through a column mapping
(Impor Jawaban). Stateless: the browser sends the file again with the mapping."""
import csv
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from autograde import db, importer
from autograde.api import deps
from autograde.api.schemas import AnswerMapping, ScoreMapping, table

router = APIRouter(tags=["imports"])
PREVIEW_ROWS = 5


def read_csv(file):
    """sep=None sniffs "," or ";" (spreadsheets in an Indonesian locale save with ";"); utf-8-sig strips a BOM."""
    data = deps.read_upload(file)
    try:
        return pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig", sep=None,
                           engine="python")
    except (ValueError, csv.Error) as e:
        raise HTTPException(422, f"{file.filename} is not a readable CSV ({e})") from None


def _mapping(model, text):
    try:
        return model.model_validate_json(text)
    except ValidationError as e:
        raise HTTPException(422, [f"mapping.{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]) from None


def _check_columns(df, columns):
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise HTTPException(422, [f"column {c!r} is not in the CSV" for c in missing])


def _course_questions(course_id, qids):
    known = {q for a in db.assessments(course_id) for q in db.questions(a["id"])}
    unknown = sorted(set(qids) - known)
    if unknown:
        raise HTTPException(422, [f"question {q} is not in this course" for q in unknown])


@router.post("/imports/preview")
def preview(file: UploadFile = File(...)):
    df = read_csv(file)
    return {"count": len(df), **table(df.head(PREVIEW_ROWS))}


@router.post("/courses/{course_id}/answers")
def import_answers(course_id: int, file: UploadFile = File(...), mapping: str = Form(...), dry_run: bool = False):
    deps.course_or_404(course_id)
    m = _mapping(AnswerMapping, mapping)
    _course_questions(course_id, m.columns)
    df = read_csv(file)
    _check_columns(df, [m.id_col, *m.name_cols,
                        *(c for s in m.columns.values() for c in (s.column, s.filter_column) if c)])
    rows, report = importer.answers_from_table(df, m.id_col, m.name_cols, m.source_map(), m.split)
    if rows and not dry_run:
        db.import_course_answers(course_id, rows)
    return {"new": len(rows), "added": 0 if dry_run else len(rows), "blank": report["blank"],
            "existing": report["existing"],
            "answers": [{k: r[k] for k in ("answer_id", "question_id", "external_id", "name", "text")} for r in rows]}


@router.post("/courses/{course_id}/scores")
def import_scores(course_id: int, file: UploadFile = File(...), mapping: str = Form(...), dry_run: bool = False):
    """Lecturer scores 0-100; an earlier score by the same rater for the same criterion is replaced."""
    deps.course_or_404(course_id)
    m = _mapping(ScoreMapping, mapping)
    _course_questions(course_id, [m.question_id])
    df = read_csv(file)
    _check_columns(df, [m.id_col, *m.columns.values()])
    scores = importer.scores_from_table(df, m.id_col, m.question_id, m.columns, m.rater_id)
    if len(scores) and not dry_run:
        db.add_human_scores(scores, replace=True)
    return {"added": 0 if dry_run else len(scores), **table(scores)}
