"""Request models (validation and the /docs page) and the one response helper for tables."""
import json
from typing import Annotated

from pydantic import BaseModel, StringConstraints

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
