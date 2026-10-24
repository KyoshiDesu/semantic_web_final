"""An assessment's grading status, the review gate, and the grade and feedback exports.

The final score of an answer is the lecturer-corrected score when there is one, else the system score.
"""
import pandas as pd

from autograde import db, feedback, gold
from autograde.models import LedgerEntry

COLUMNS = ["answer_id", "question_id", "external_id", "name", "source", "status", "score", "final", "flagged",
           "contradictions", "reviewed_by"]
DRAFT_MARK = "# DRAF — belum semua jawaban ditinjau\n"


def _ledger(r):
    return r["ledger_corrected"] or r["ledger"]


def status_table(assessment_id, run_id):
    """One row per answer: belum dinilai / usang (key edited after grading) / dinilai / ditinjau."""
    answers, results = db.assessment_answers(assessment_id), db.results(run_id)
    updated = db.question_updated(set(answers.question_id))
    rows = []
    for a in answers.itertuples():
        r = results.get(a.answer_id)
        if r is None:
            rows.append([a.answer_id, a.question_id, a.external_id, a.name, a.source, "belum dinilai", None, None,
                         0, 0, None])
            continue
        stale = bool(updated.get(a.question_id) and r["graded"] and r["graded"] < updated[a.question_id])
        status = "usang" if stale else "ditinjau" if r["reviewed"] else "dinilai"
        ledger = _ledger(r)
        rows.append([a.answer_id, a.question_id, a.external_id, a.name, a.source, status, r["score"]["score"],
                     (r["score_corrected"] or r["score"])["score"], sum(e["needs_review"] for e in ledger),
                     sum(e["status"] == "CONTRADICTED" for e in ledger), r["reviewed_by"]])
    return pd.DataFrame(rows, columns=COLUMNS)


def bulk_approvable(table):
    """Graded, up-to-date answers the system is confident about: no ⚑ entry and no contradiction."""
    ok = (table.status == "dinilai") & (table.flagged == 0) & (table.contradictions == 0)
    return table[ok].answer_id.tolist()


def ready(table):
    return len(table) > 0 and bool((table.status == "ditinjau").all())


def grades_csv(table, qids, draft=False):
    """One row per student: final score per question (blank = no answer) and the mean, where no answer counts 0."""
    out = table.drop_duplicates("external_id").set_index("external_id")[["name"]]
    out = out.join(table.pivot(index="external_id", columns="question_id", values="final").reindex(columns=qids))
    out["rata_rata"] = out[qids].astype(float).fillna(0).mean(axis=1)
    out[[*qids, "rata_rata"]] = out[[*qids, "rata_rata"]].astype(float).round(1)
    if draft:
        reviewed = table.assign(r=table.status == "ditinjau").groupby("external_id").r
        out["status"] = [f"{reviewed.sum()[s]}/{reviewed.count()[s]} ditinjau" for s in out.index]
    text = out.reset_index().fillna({"name": ""}).to_csv(index=False)
    return DRAFT_MARK + text if draft else text


def feedback_csv(table, run_id):
    """One row per graded answer. A corrected answer gets template feedback rebuilt from the corrected ledger, so
    the feedback agrees with the final score."""
    results, refs, rows = db.results(run_id), {}, []
    for t in table[table.status != "belum dinilai"].itertuples():
        r = results[t.answer_id]
        fb = r["feedback"]
        if r["score_corrected"]:
            if t.question_id not in refs:
                refs[t.question_id] = gold.load(t.question_id)[2]
            fb = feedback.template(t.answer_id, [LedgerEntry(**e) for e in r["ledger_corrected"]],
                                   refs[t.question_id], r["score_corrected"]["score"]).model_dump()
        rows.append([t.external_id, t.name or "", t.question_id, round(t.final, 1), t.status, fb["summary"],
                     "\n".join(c["text"] for c in fb["claims"])])
    return pd.DataFrame(rows, columns=["external_id", "name", "question_id", "nilai", "status", "ringkasan",
                                       "umpan_balik"]).to_csv(index=False)
