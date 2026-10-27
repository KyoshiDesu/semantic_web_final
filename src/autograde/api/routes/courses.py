"""Courses, assessments and students (Streamlit: Mata Kuliah)."""
from fastapi import APIRouter

from autograde import db
from autograde.api import deps
from autograde.api.schemas import AssessmentIn, CourseIn, table

router = APIRouter(tags=["courses"])


@router.get("/courses")
def list_courses():
    return db.courses()


@router.post("/courses", status_code=201)
def add_course(body: CourseIn):
    return db.course(db.add_course(body.code, body.name))


@router.get("/courses/{course_id}/assessments")
def list_assessments(course_id: int):
    deps.course_or_404(course_id)
    return [{**a, "questions": db.questions(a["id"])} for a in db.assessments(course_id)]


@router.post("/courses/{course_id}/assessments", status_code=201)
def add_assessment(course_id: int, body: AssessmentIn):
    deps.course_or_404(course_id)
    return db.assessment(db.add_assessment(course_id, body.name))


@router.get("/courses/{course_id}/students")
def list_students(course_id: int):
    deps.course_or_404(course_id)
    return table(db.students(course_id))
