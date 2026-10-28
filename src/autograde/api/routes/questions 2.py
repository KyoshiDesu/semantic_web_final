"""Questions: list, read, save from the editor's tables, live preview, file upload and download (Editor Soal)."""
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from autograde import authoring, db, extract, gold, importer, io, kg, rdfviz
from autograde.api import deps
from autograde.api.schemas import NewQuestion, PreviewRequest, QuestionDraft

router = APIRouter(tags=["questions"])


def _summary(qid, counts):
    q = db.question(qid)
    return {"id": qid, "assessment_id": q["assessment_id"], "prompt": q["prompt"],
            "language": q["rubric"].get("language", "id"), "answers": int(counts.get(qid, 0)),
            "results": db.result_count(qid)}


def _answer_counts():
    return db.answers(include_synthetic=True).question_id.value_counts()


def _checked(qid, draft, base):
    try:
        return authoring.from_tables(qid, draft.tables(), base)
    except ValueError as e:  # e.g. a concept listed twice; save_question validates the rest
        raise HTTPException(422, [str(e)]) from None


@router.get("/questions")
def list_questions():
    counts = _answer_counts()
    return [_summary(q, counts) for q in db.questions()]


@router.get("/assessments/{assessment_id}/questions")
def assessment_questions(assessment_id: int):
    deps.assessment_or_404(assessment_id)
    counts = _answer_counts()
    return [_summary(q, counts) for q in db.questions(assessment_id)]


@router.get("/questions/{qid}")
def get_question(qid: str):
    q = deps.question_or_404(qid)
    return {**q, "draft": QuestionDraft.from_tables(authoring.to_tables(q)), "results": db.result_count(qid)}


@router.post("/questions", status_code=201)
def create_question(body: NewQuestion):
    deps.assessment_or_404(body.assessment_id)
    rubric, gold_raw = _checked(body.id, body.draft, None)
    importer.save_question(body.id, body.draft.prompt.strip(), body.draft.reference_answer.strip(), rubric, gold_raw,
                           body.assessment_id)
    return {"id": body.id}


@router.put("/questions/{qid}")
def update_question(qid: str, draft: QuestionDraft):
    base = deps.question_or_404(qid)
    rubric, gold_raw = _checked(qid, draft, base)
    importer.save_question(qid, draft.prompt.strip(), draft.reference_answer.strip(), rubric, gold_raw)
    return {"id": qid, "stale_results": db.result_count(qid)}


@router.post("/questions/preview")
def preview(body: PreviewRequest):
    """The live preview: the validation errors, or the gold graph this draft would store. Nothing is saved."""
    base = deps.question_or_404(body.base_id) if body.base_id else None
    d = body.draft
    try:
        rubric, gold_raw = authoring.from_tables(body.id, d.tables(), base)
        refs = importer.validate_question(d.prompt.strip(), d.reference_answer.strip(), rubric, gold_raw,
                                          importer.checked_relations())
    except ValueError as e:
        return {"valid": False, "errors": str(e).split("; ")}
    files = authoring.question_files(d.prompt, d.reference_answer, rubric, gold_raw)
    return {"valid": True, "errors": [], "graph": kg.gold_graph_name(body.id),
            "concept_dot": rdfviz.gold_concept_dot(refs, gold_raw["concepts"]),
            "reified_dot": rdfviz.gold_reified_dot(body.id, refs),
            "turtle": gold.to_graph(body.id, refs, rubric, gold_raw["concepts"]).serialize(format="turtle"),
            "yaml": files["rubric.yaml"] + "\n---\n" + files["gold.yaml"]}


@router.post("/assessments/{assessment_id}/questions/upload", status_code=201)
def upload_question(assessment_id: int, files: list[UploadFile] = File(...)):
    """The four files of data/questions/<qid>/ (question.md, reference_answer.md, rubric.yaml, gold.yaml)."""
    deps.assessment_or_404(assessment_id)
    try:
        texts = {f.filename: deps.read_upload(f).decode("utf-8") for f in files}
    except UnicodeDecodeError as e:
        raise HTTPException(422, f"question files must be UTF-8 text ({e})") from None
    return {"id": importer.add_question(assessment_id, texts)}


@router.get("/questions/{qid}/files.zip")
def question_zip(qid: str):
    q = deps.question_or_404(qid)
    files = authoring.question_files(q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    return Response(authoring.question_zip(qid, files), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{qid}.zip"'})


@router.get("/predicates")
def predicates(lang: Literal["id", "en"] = "id"):
    """The predicates a key in this language may use (the editor's dropdown); `other` is only for extraction."""
    return [p for p in extract.for_language(io.load_predicates(), lang)["predicates"] if p["id"] != "other"]
