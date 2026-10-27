"""Request models (validation and the /docs page) and the one response helper for tables."""
import json
from typing import Annotated, Literal

import pandas as pd
from pydantic import BaseModel, Field, StringConstraints, model_validator

from autograde import authoring
from autograde.models import Status

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def table(df):
    """A DataFrame as {columns, rows}: NaN and None become null, numpy numbers plain JSON numbers."""
    data = json.loads(df.to_json(orient="split", index=False, date_format="iso"))
    return {"columns": data["columns"], "rows": data["data"]}


class CourseIn(BaseModel):
    code: Name
    name: Name


class AssessmentIn(BaseModel):
    name: Name


QuestionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]


class CriterionRow(BaseModel):
    id: str = ""
    description: str = ""


class ConceptRow(BaseModel):
    concept: str = ""
    aliases: list[str] = []
    broader: list[str] = []


class TripleRow(BaseModel):
    id: str = ""
    s: list[str] = []
    p: str = ""
    o: str = ""
    criterion: str = ""
    weight: float | None = None


class QuestionDraft(BaseModel):
    """The editor's tables (authoring.to_tables) as JSON."""
    prompt: str = ""
    reference_answer: str = ""
    language: Literal["id", "en"] = "id"
    validated_by: str = ""
    criteria: list[CriterionRow] = []
    concepts: list[ConceptRow] = []
    triples: list[TripleRow] = []

    def tables(self):
        def frame(rows, columns):
            return pd.DataFrame([r.model_dump() for r in rows], columns=columns)
        return {"prompt": self.prompt, "reference_answer": self.reference_answer, "language": self.language,
                "validated_by": self.validated_by, "criteria": frame(self.criteria, authoring.CRITERIA),
                "concepts": frame(self.concepts, authoring.CONCEPTS), "triples": frame(self.triples, authoring.TRIPLES)}

    @classmethod
    def from_tables(cls, draft):
        return cls(**{k: json.loads(v.to_json(orient="records")) if isinstance(v, pd.DataFrame) else v
                      for k, v in draft.items()})


class NewQuestion(BaseModel):
    id: QuestionId
    assessment_id: int
    draft: QuestionDraft


class PreviewRequest(BaseModel):
    id: QuestionId
    draft: QuestionDraft
    base_id: str | None = None  # the question edited or copied: its keys the editor doesn't manage are kept


class AnswerSource(BaseModel):
    """One question's answers: a column of a wide table, or a long table's rows where filter_column == filter_value."""
    column: str
    filter_column: str | None = None
    filter_value: str | None = None

    @model_validator(mode="after")
    def _filter_pair(self):
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError("filter_column and filter_value go together")
        return self


class AnswerMapping(BaseModel):
    id_col: str
    name_cols: list[str] = []
    columns: dict[str, AnswerSource] = Field(min_length=1)
    split: Literal["pilot", "test"] = "test"

    def source_map(self):
        """importer.answers_from_table's form: qid -> (answer column, None | (question column, value))."""
        return {q: (s.column, (s.filter_column, s.filter_value) if s.filter_column else None)
                for q, s in self.columns.items()}


class ScoreMapping(BaseModel):
    id_col: str
    question_id: str
    columns: dict[str, str] = Field(min_length=1)  # criterion id, or "_total" for a holistic score -> column
    rater_id: Name = "D1"


class GradingRequest(BaseModel):
    which: Literal["new", "stale"] = "new"
    llm_feedback: bool = False


class ReviewerIn(BaseModel):
    by: Name


class Correction(BaseModel):
    reference_id: str
    status: Status
    reason: Name


class CorrectionsIn(BaseModel):
    by: Name
    corrections: list[Correction] = Field(min_length=1)


class SparqlIn(BaseModel):
    query: str = Field(min_length=1)
    graphs: list[str] | None = None  # named graphs (plus the ontology) queried with rdflib; None: the whole store
