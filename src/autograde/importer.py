"""One-time import of the file-based data/ folder into SQLite + Oxigraph. The only module that reads data/.

Everything is read and validated first; the existing stores are only deleted once the new data is known good.
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from autograde import db, extract, gold, io, kg

DEMO_COURSE = ("DEMO", "Contoh dek (synthetic)")
DEMO_ASSESSMENT = "Impor dari data/"
OVERRIDE_KEYS = set(db.OVERRIDE_KEYS)
QUESTION_FILES = ("question.md", "reference_answer.md", "rubric.yaml", "gold.yaml")
BLANK = {"", "-"}  # "-" is Moodle's "no response"


class ImportDataError(ValueError):
    pass


def validate_question(prompt, reference_answer, rubric, gold_raw, relations):
    """The reference triples of one question, or an error naming what is wrong."""
    if not isinstance(rubric, dict) or not isinstance(rubric.get("criteria"), list):
        raise ImportDataError("rubric.yaml needs a list of criteria")
    if not isinstance(gold_raw, dict):
        raise ImportDataError("gold.yaml must be a mapping")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(rubric.get("question_id") or "")):
        raise ImportDataError(f"question_id {rubric.get('question_id')!r}: use letters, digits, _ or -")
    if not prompt or not reference_answer:
        raise ImportDataError("question.md and reference_answer.md must not be empty")
    return gold.validate(gold_raw, rubric, relations)


def _relations():
    relations, _, _ = io.ontology_relations()
    gold.check_predicates(io.load_predicates(), relations)
    return relations


def read_questions(data_dir):
    relations = _relations()
    out = {}
    for d in sorted(p for p in (data_dir / "questions").iterdir() if (p / "gold.yaml").exists()):
        gold_raw, rubric = io.load_yaml(d / "gold.yaml"), io.load_yaml(d / "rubric.yaml")
        prompt = (d / "question.md").read_text(encoding="utf-8").strip()
        ref = (d / "reference_answer.md").read_text(encoding="utf-8").strip()
        out[d.name] = {"prompt": prompt, "reference_answer": ref, "rubric": rubric, "gold": gold_raw,
                       "refs": validate_question(prompt, ref, rubric, gold_raw, relations)}
    return out


def add_question(assessment_id, files):
    """One question from its four uploaded files ({file name: text}), in the format of data/questions/Q1."""
    missing = [f for f in QUESTION_FILES if f not in files]
    if missing:
        raise ImportDataError(f"missing files: {', '.join(missing)}")
    parsed = {}
    for f in ("rubric.yaml", "gold.yaml"):
        try:
            parsed[f] = yaml.safe_load(files[f])
        except yaml.YAMLError as e:
            raise ImportDataError(f"{f}: {e}") from e
    rubric, gold_raw = parsed["rubric.yaml"], parsed["gold.yaml"]
    prompt, ref = files["question.md"].strip(), files["reference_answer.md"].strip()
    refs = validate_question(prompt, ref, rubric, gold_raw, _relations())
    qid = rubric["question_id"]
    if qid in db.questions():
        raise ImportDataError(f"question {qid} already exists; change question_id in rubric.yaml and gold.yaml")
    db.add_question(qid, assessment_id, prompt, ref, rubric, gold_raw)
    kg.put_graph(kg.gold_graph_name(qid), gold.to_graph(qid, refs, rubric, gold_raw.get("concepts")))
    return qid


# ---------- LMS exports (column-mapped CSV tables) ----------

def slug(s):
    """Answer ids end up in IRIs."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", s)


def _cell(v):
    return "" if v is None or pd.isna(v) else str(v).strip()


def answers_from_table(df, id_col, name_cols, columns, split):
    """Answer rows from an LMS table. columns maps qid -> (answer column, filter): filter is None for a wide table
    (one row per student) or (question column, value) for a long one (one row per answer).
    Returns (rows, report); answers already in the database are reported, not returned."""
    if split not in ("pilot", "test"):
        raise ImportDataError(f"split {split!r} (pilot or test)")
    existing = db.answer_ids(columns)
    rows, report, errors = [], {"blank": 0, "existing": []}, []
    for qid, (answer_col, filt) in columns.items():
        sub = df if filt is None else df[df[filt[0]].map(_cell) == filt[1]]
        seen = {}
        for r in sub.to_dict("records"):
            ext, text = _cell(r[id_col]), _cell(r[answer_col])
            if not ext:
                errors.append(f"{qid}: a row has no student id in column {id_col!r}")
                continue
            if text in BLANK:
                report["blank"] += 1
                continue
            aid = f"{qid}_{slug(ext)}"
            if aid in seen:
                errors.append(f"{qid}: student {ext} appears twice" if seen[aid] == ext
                              else f"{qid}: student ids {seen[aid]!r} and {ext!r} give the same answer id {aid}")
                continue
            seen[aid] = ext
            if aid in existing:
                report["existing"].append(aid)
                continue
            name = " ".join(n for n in (_cell(r[c]) for c in name_cols) if n) or None
            rows.append({"answer_id": aid, "question_id": qid, "external_id": ext, "name": name, "text": text,
                         "split": split, "source": "real"})
    if errors:
        raise ImportDataError("; ".join(errors))
    return rows, report


def scores_from_table(df, id_col, qid, columns, rater_id):
    """Human scores (0-100) from an LMS table: columns maps criterion -> column. Rows without any score are skipped."""
    criteria = {c["id"] for c in db.question(qid)["rubric"]["criteria"]} | {io.TOTAL}
    unknown = sorted(set(columns) - criteria)
    if unknown or not rater_id.strip():
        raise ImportDataError(f"unknown criteria {unknown}" if unknown else "rater id is empty")
    known = db.answer_ids([qid])
    out, errors, seen = [], [], set()
    for r in df.to_dict("records"):
        ext = _cell(r[id_col])
        values = {crit: _cell(r[col]) for crit, col in columns.items()}
        if all(v in BLANK for v in values.values()):
            continue
        aid = f"{qid}_{slug(ext)}"
        if aid not in known:
            errors.append(f"student {ext!r} has no answer to {qid}")
            continue
        if aid in seen:
            errors.append(f"student {ext} appears twice")
            continue
        seen.add(aid)
        for crit, v in values.items():
            if v in BLANK:
                continue
            try:
                x = float(v.replace(",", "."))  # decimal comma from Indonesian spreadsheets
            except ValueError:
                errors.append(f"student {ext}, {crit}: {v!r} is not a number")
                continue
            if not 0 <= x <= 100:
                errors.append(f"student {ext}, {crit}: {v} is outside 0-100")
                continue
            out.append([aid, rater_id.strip(), crit, x])
    if errors:
        raise ImportDataError("; ".join(errors))
    return pd.DataFrame(out, columns=db.SCORE_COLUMNS)


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
                extract.extract_gold(a.answer_id, annotation=annotation, predicates=predicates)  # predicate check
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
