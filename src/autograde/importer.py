"""One-time import of the file-based data/ folder into SQLite + Oxigraph. The only module that reads data/.

Everything is read and validated first; the existing stores are only deleted once the new data is known good.
"""
from pathlib import Path

import pandas as pd

from autograde import db, extract, gold, io, kg

DEMO_COURSE = ("DEMO", "Contoh dek (synthetic)")
DEMO_ASSESSMENT = "Impor dari data/"
OVERRIDE_KEYS = set(db.OVERRIDE_KEYS)


class ImportDataError(ValueError):
    pass


def read_questions(data_dir):
    relations, _, _ = io.ontology_relations()
    gold.check_predicates(io.load_predicates(), relations)
    out = {}
    for d in sorted(p for p in (data_dir / "questions").iterdir() if (p / "gold.yaml").exists()):
        gold_raw, rubric = io.load_yaml(d / "gold.yaml"), io.load_yaml(d / "rubric.yaml")
        out[d.name] = {"prompt": (d / "question.md").read_text(encoding="utf-8").strip(),
                       "reference_answer": (d / "reference_answer.md").read_text(encoding="utf-8").strip(),
                       "rubric": rubric, "gold": gold_raw, "refs": gold.validate(gold_raw, rubric, relations)}
    return out


def read_answers(data_dir, question_ids):
    predicates = io.load_predicates()
    rows = []
    for csv, source, ann_dir in ((data_dir / "answers" / "answers.csv", "real", data_dir / "annotations"),
                                 (data_dir / "synthetic" / "answers.csv", "synthetic",
                                  data_dir / "synthetic" / "annotations")):
        if not csv.exists():
            continue
        for a in pd.read_csv(csv, dtype=str).itertuples():
            if a.question_id not in question_ids:
                raise ImportDataError(f"{csv}: {a.answer_id} refers to unknown question {a.question_id}")
            if a.split not in ("pilot", "test"):
                raise ImportDataError(f"{csv}: {a.answer_id} has split {a.split!r} (pilot or test)")
            ann_path = ann_dir / f"{a.answer_id}.yaml"
            annotation = io.load_yaml(ann_path) if ann_path.exists() else None
            if annotation is not None:
                extract.extract_gold(a.answer_id, path=ann_path, predicates=predicates)  # predicate check
            rows.append({"answer_id": a.answer_id, "question_id": a.question_id, "text": a.text, "split": a.split,
                         "source": source, "annotation": annotation})
    ids = [r["answer_id"] for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ImportDataError(f"answer_id must be globally unique; duplicates: {dupes}")
    return rows


def read_scores(data_dir, answer_ids):
    paths = (data_dir / "human" / "scores.csv", data_dir / "synthetic" / "scores.csv")
    scores = pd.concat([io.load_scores(p) for p in paths], ignore_index=True)
    unknown = sorted(set(scores.answer_id) - answer_ids)
    if unknown:
        raise ImportDataError(f"human scores for unknown answers: {unknown}")
    return scores


def read_overrides(data_dir, answer_ids):
    path = data_dir / "human" / "overrides.yaml"
    rows = (io.load_yaml(path) or []) if path.exists() else []
    for r in rows:
        if not OVERRIDE_KEYS <= set(r) or r["answer_id"] not in answer_ids:
            raise ImportDataError(f"{path}: bad override {r}")
    return rows


def read_audit(data_dir):
    path = data_dir / "human" / "evidence_audit.csv"
    return pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=db.AUDIT_COLUMNS)


def import_files(replace=False, data_dir=None):
    data_dir = Path(data_dir or io.ROOT / "data")
    if not replace and db.db_path().exists() and not db.is_empty():
        raise ImportDataError("the database is not empty; use `python -m autograde db import --replace` "
                              "to rebuild it from data/")
    questions = read_questions(data_dir)
    answers = read_answers(data_dir, set(questions))
    ids = {a["answer_id"] for a in answers}
    scores, overrides, audit = read_scores(data_dir, ids), read_overrides(data_dir, ids), read_audit(data_dir)

    kg.remove()
    db.remove()
    db.connect(create=True).close()
    assessment = db.add_assessment(db.add_course(*DEMO_COURSE), DEMO_ASSESSMENT)
    for qid, q in questions.items():
        db.add_question(qid, assessment, q["prompt"], q["reference_answer"], q["rubric"], q["gold"])
    db.add_answers(answers)
    db.add_human_scores(scores)
    db.add_overrides(overrides)
    db.add_evidence_audit(audit)
    for qid, q in questions.items():
        kg.put_graph(kg.gold_graph_name(qid), gold.to_graph(qid, q["refs"], q["rubric"], q["gold"].get("concepts")))
    kg.sync_ontology()
    return {"questions": len(questions), "answers": len(answers), "human_scores": len(scores),
            "overrides": len(overrides), "evidence_audit": len(audit)}
