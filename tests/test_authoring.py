"""Question editor tables <-> rubric and gold-key dicts, and the downloadable files."""
import io as _io
import zipfile

import pandas as pd
import pytest

from autograde import authoring, db, importer


def test_q1_round_trip():
    q = db.question("Q1")
    rubric, gold_raw = authoring.from_tables("Q1", authoring.to_tables(q), q)
    assert rubric == {**q["rubric"], "language": "id"}
    assert gold_raw == q["gold"]


def test_blank_rows_ids_and_kept_keys():
    q = db.question("Q1")
    q = {**q, "gold": {**q["gold"], "drafted_by": "LLM"}}
    draft = authoring.to_tables(q)
    draft["criteria"].loc[len(draft["criteria"])] = [None, None]
    draft["concepts"].loc[len(draft["concepts"])] = ["", ["x"], []]
    t = draft["triples"]
    t.loc[len(t)] = [None, None, None, None, None, None]
    t.loc[len(t)] = [None, ["Tumbuhan"], "menghasilkan", "Gas", "K2_Produk", None]
    t.loc[0, "id"] = None
    draft["validated_by"] = " Dr. Ani "
    rubric, gold_raw = authoring.from_tables("Q1", draft, q)
    assert len(rubric["criteria"]) == 3 and len(gold_raw["concepts"]) == len(q["gold"]["concepts"])
    assert [t["id"] for t in gold_raw["triples"]] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert gold_raw["triples"][-1]["weight"] == 1 and gold_raw["drafted_by"] == "LLM"
    assert gold_raw["validated_by"] == "Dr. Ani" and gold_raw["validated_on"]
    draft["concepts"].loc[len(draft["concepts"])] = ["Air", [], []]
    with pytest.raises(ValueError, match="concept Air is listed twice"):
        authoring.from_tables("Q1", draft, q)


def test_empty_tables_give_a_minimal_draft():
    draft = authoring.empty_tables()
    assert draft["criteria"].id.tolist() == ["K1"] and draft["triples"].empty
    rubric, gold_raw = authoring.from_tables("QX", draft)
    assert rubric == {"question_id": "QX", "criteria": [{"id": "K1", "description": ""}], "language": "id"}
    assert gold_raw["concepts"] == {} and gold_raw["validated_on"] is None


def test_files_and_zip_round_trip_through_the_upload(fresh_db):
    importer.import_files()
    q = db.question("Q1")
    rubric, gold_raw = authoring.from_tables("Q1Z", authoring.to_tables(q), q)
    files = authoring.question_files(q["prompt"], q["reference_answer"], rubric, gold_raw)
    with zipfile.ZipFile(_io.BytesIO(authoring.question_zip("Q1Z", files))) as z:
        assert sorted(z.namelist()) == sorted(f"Q1Z/{f}" for f in importer.QUESTION_FILES)
        unzipped = {n.split("/")[1]: z.read(n).decode("utf-8") for n in z.namelist()}
    assert importer.add_question(db.assessments(db.courses()[0]["id"])[0]["id"], unzipped) == "Q1Z"
    stored = db.question("Q1Z")
    assert stored["gold"] == gold_raw and stored["prompt"] == q["prompt"]
    assert pd.DataFrame(stored["gold"]["triples"]).weight.tolist() == [2, 2, 2, 2, 2]
