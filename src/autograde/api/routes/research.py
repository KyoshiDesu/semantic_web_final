"""Research results, read-only: runs, their evaluation reports and figures. Calibration, research runs and evaluate
stay CLI commands (Evaluasi)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from autograde import db, evaluate
from autograde.api import deps

router = APIRouter(tags=["research"])


def _figures(run_id):
    d = evaluate.report_dir(run_id)
    return sorted(p.name for p in d.glob("*.png")) if d.is_dir() else []


@router.get("/runs")
def runs():
    """Newest first; the report text is left out of the list."""
    return [{**{k: v for k, v in r.items() if k != "evaluation_md"}, "has_evaluation": bool(r["evaluation_md"]),
             "results": len(db.result_ids(r["run_id"]))} for r in db.runs(finished_only=False)]


@router.get("/runs/{run_id}")
def run(run_id: str):
    return {**deps.run_or_404(run_id), "results": len(db.result_ids(run_id)), "figures": _figures(run_id)}


@router.get("/runs/{run_id}/figures/{name}")
def figure(run_id: str, name: str):
    deps.run_or_404(run_id)
    if name not in _figures(run_id):  # only names listed in the report folder, so no path can leave it
        raise HTTPException(404, f"no figure {name} for run {run_id}")
    return FileResponse(evaluate.report_dir(run_id) / name, media_type="image/png")
