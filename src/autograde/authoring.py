"""Question editor: the tables a lecturer edits <-> the rubric and gold-key dicts stored in the database.

Validation is not done here; importer.validate_question checks the dicts from_tables returns.
"""
import io as _io
import zipfile
from datetime import date

import pandas as pd
import yaml

CRITERIA = ["id", "description"]
CONCEPTS = ["concept", "aliases", "broader"]
TRIPLES = ["id", "s", "p", "o", "criterion", "weight"]
BLANK_QUESTION = {"prompt": "", "reference_answer": "", "rubric": {"criteria": [{"id": "K1", "description": ""}]},
                  "gold": {"concepts": {}, "triples": []}}


def _str(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _list(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    return [s for s in (_str(x) for x in ([v] if isinstance(v, str) else v)) if s]


def to_tables(q):
    """A db.question() dict as the editor's draft: texts plus criteria, concepts and triples DataFrames."""
    rubric, g = q["rubric"], q["gold"]
    triples = pd.DataFrame([[t["id"], _list(t["s"]), t["p"], t["o"], t["criterion"], t["weight"]]
                            for t in g.get("triples") or []], columns=TRIPLES)
    return {"prompt": q["prompt"], "reference_answer": q["reference_answer"], "language": rubric.get("language", "id"),
            "validated_by": g.get("validated_by") or "",
            "criteria": pd.DataFrame([[c["id"], c.get("description", "")] for c in rubric["criteria"]],
                                     columns=CRITERIA),
            "concepts": pd.DataFrame([[c, _list((v or {}).get("aliases")), _list((v or {}).get("broader"))]
                                      for c, v in (g.get("concepts") or {}).items()], columns=CONCEPTS),
            "triples": triples.astype({"weight": float})}


def empty_tables():
    return to_tables(BLANK_QUESTION)


def from_tables(qid, draft, base=None):
    """(rubric, gold_raw) from the draft. Blank rows are dropped, blank triple ids become the next free R<n>, and
    keys of the base question that the editor does not manage (e.g. drafted_by) are kept."""
    base = base or BLANK_QUESTION
    criteria = [{"id": _str(r["id"]), "description": _str(r["description"])}
                for r in draft["criteria"].to_dict("records") if _str(r["id"]) or _str(r["description"])]
    concepts = {}
    for r in draft["concepts"].to_dict("records"):
        name = _str(r["concept"])
        if not name:
            continue
        if name in concepts:
            raise ValueError(f"concept {name} is listed twice")
        aliases, broader = _list(r["aliases"]), _list(r["broader"])
        concepts[name] = {**({"aliases": aliases} if aliases else {}), **({"broader": broader} if broader else {})}
    rows = [r for r in draft["triples"].to_dict("records")
            if any(_str(r[k]) for k in ("id", "p", "o", "criterion")) or _list(r["s"])]
    used, n, triples = {_str(r["id"]) for r in rows}, 1, []
    for r in rows:
        tid = _str(r["id"])
        if not tid:
            while f"R{n}" in used:
                n += 1
            tid = f"R{n}"
        used.add(tid)
        w = r["weight"]
        w = 1 if w is None or pd.isna(w) else float(w)
        triples.append({"id": tid, "s": _list(r["s"]), "p": _str(r["p"]), "o": _str(r["o"]),
                        "criterion": _str(r["criterion"]), "weight": int(w) if w.is_integer() else w})
    name = _str(draft["validated_by"])
    # question_id is repeated so it comes first in the YAML but always wins over the base question's value
    rubric = {"question_id": qid, **base["rubric"], "question_id": qid, "language": draft["language"],
              "criteria": criteria}
    gold_raw = {"question_id": qid, **base["gold"], "question_id": qid, "validated_by": name or None,
                "validated_on": date.today().isoformat() if name else None, "concepts": concepts, "triples": triples}
    return rubric, gold_raw


def question_files(prompt, reference_answer, rubric, gold_raw):
    """The four files of data/questions/<qid>/, as importer.add_question accepts them."""
    dump = lambda d: yaml.safe_dump(d, allow_unicode=True, sort_keys=False)  # noqa: E731
    return {"question.md": prompt.strip() + "\n", "reference_answer.md": reference_answer.strip() + "\n",
            "rubric.yaml": dump(rubric), "gold.yaml": dump(gold_raw)}


def question_zip(qid, files):
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(f"{qid}/{name}", text)
    return buf.getvalue()
