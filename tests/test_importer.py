"""db import: Q1 + synthetic data into both stores; refuses to overwrite; validates before touching anything."""
import shutil

import pandas as pd
import pytest
from rdflib import Literal

from autograde import db, gold, importer, io, kg

SYNTHETIC = ["Q1_A07", "Q1_A08", "Q1_S01", "Q1_S02", "Q1_S03", "Q1_S04", "Q1_S05"]


def canon(g):
    """Triples with literals compared by value: Oxigraph stores decimals canonically ("2.0" -> "2")."""
    return {(s, p, o.toPython() if isinstance(o, Literal) else o) for s, p, o in g}


def test_import_loads_q1_and_synthetic_data():
    assert db.questions() == ["Q1"]
    q = db.question("Q1")
    assert q["gold"] == io.load_yaml(io.ROOT / "data" / "questions" / "Q1" / "gold.yaml")
    assert "fotosintesis" in q["prompt"].lower()
    answers = db.answers(include_synthetic=True)
    assert sorted(answers.answer_id) == SYNTHETIC
    assert set(answers.source) == {"synthetic"} and answers.annotated.all()
    assert db.answers().empty  # no real answers are bundled
    assert db.annotation("Q1_S04") == {"triples": []}
    expected = io.load_scores(io.ROOT / "data" / "synthetic" / "scores.csv")
    assert len(db.human_scores(include_synthetic=True)) == len(expected)


def test_gold_graph_matches_the_yaml_key():
    q = db.question("Q1")
    relations, _, _ = io.ontology_relations()
    refs = gold.validate(q["gold"], q["rubric"], relations)
    stored = kg.get_graph(kg.gold_graph_name("Q1"))
    assert canon(stored) == canon(gold.to_graph("Q1", refs, q["rubric"], q["gold"]["concepts"]))
    assert len(kg.get_graph(kg.ONTOLOGY)) > 100


def test_import_refuses_a_non_empty_database():
    with pytest.raises(importer.ImportDataError, match="--replace"):
        importer.import_files()


def test_invalid_data_aborts_before_touching_the_database(fresh_db, tmp_path):
    counts = importer.import_files()
    assert counts["questions"] == 1 and counts["answers"] == 7
    data = tmp_path / "data"
    shutil.copytree(io.ROOT / "data" / "questions" / "Q1", data / "questions" / "Q1")
    raw = io.load_yaml(data / "questions" / "Q1" / "gold.yaml")
    raw["triples"][0]["p"] = "memasak"
    io.save_yaml(raw, data / "questions" / "Q1" / "gold.yaml")
    with pytest.raises(gold.GoldError, match="unknown predicate"):
        importer.import_files(replace=True, data_dir=data)
    assert db.questions() == ["Q1"] and len(db.answers(include_synthetic=True)) == 7
    assert kg.has_graph(kg.gold_graph_name("Q1"))


def test_answer_for_unknown_question_is_rejected(fresh_db, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(io.ROOT / "data" / "questions" / "Q1", data / "questions" / "Q1")
    (data / "answers").mkdir()
    (data / "answers" / "answers.csv").write_text("answer_id,question_id,text,split\nQ7_A1,Q7,x,test\n")
    with pytest.raises(importer.ImportDataError, match="unknown question Q7"):
        importer.import_files(data_dir=data)


def test_io_reads_the_database():
    assert io.question_ids() == ["Q1"]
    assert io.load_answers().empty and len(io.load_answers(include_synthetic=True)) == 7
    assert set(io.load_human_scores(include_synthetic=True).answer_id) <= set(SYNTHETIC)


# ---------- in-app data entry ----------

Q1_DIR = io.ROOT / "data" / "questions" / "Q1"


def q1_files(qid="Q1B"):
    files = {f: (Q1_DIR / f).read_text(encoding="utf-8") for f in importer.QUESTION_FILES}
    for f in ("rubric.yaml", "gold.yaml"):
        files[f] = files[f].replace("question_id: Q1", f"question_id: {qid}")
    return files


@pytest.fixture
def course(fresh_db):
    importer.import_files()
    c = db.add_course("BIO1", "Biologi")
    return c, db.add_assessment(c, "UTS")


def test_add_question_from_files(course):
    assert importer.add_question(course[1], q1_files()) == "Q1B"
    assert db.questions(course[1]) == ["Q1B"] and db.question("Q1B")["gold"]["question_id"] == "Q1B"
    assert len(kg.get_graph(kg.gold_graph_name("Q1B"))) > 0
    with pytest.raises(importer.ImportDataError, match="already exists"):
        importer.add_question(course[1], q1_files())


def test_add_question_rejects_bad_files(course):
    files = q1_files()
    with pytest.raises(importer.ImportDataError, match="missing files: gold.yaml"):
        importer.add_question(course[1], {k: v for k, v in files.items() if k != "gold.yaml"})
    with pytest.raises(importer.ImportDataError, match="rubric.yaml"):
        importer.add_question(course[1], {**files, "rubric.yaml": "criteria: [unclosed"})
    with pytest.raises(gold.GoldError, match="unknown predicate"):
        importer.add_question(course[1], {**files, "gold.yaml": files["gold.yaml"].replace("p: menggunakan,", "p: memasak,")})
    assert db.questions(course[1]) == [] and not kg.has_graph(kg.gold_graph_name("Q1B"))


def wide():
    return pd.DataFrame({"ID": ["101", "102", "103", "104"], "First": ["Ani", "Budi", "Citra", "Dewi"],
                         "Last": ["S", "", "T", "U"], "R1": ["Fotosintesis ...", "x", "-", ""]})


def test_dataset_questions_are_valid():
    """datasets/ keys use relations nothing else uses (menghadapi, menyebabkan); removing one breaks their upload."""
    folders = [d for d in (io.ROOT / "datasets").iterdir() if (d / "questions").is_dir()]
    assert folders and all(importer.read_questions(d) for d in folders)


def test_wide_and_long_tables_give_the_same_rows(course):
    rows, report = importer.answers_from_table(wide(), "ID", ["First", "Last"], {"Q1": ("R1", None)}, "test")
    assert [r["answer_id"] for r in rows] == ["Q1_101", "Q1_102"] and report == {"blank": 2, "existing": []}
    assert [r["name"] for r in rows] == ["Ani S", "Budi"] and {r["source"] for r in rows} == {"real"}
    long = wide().assign(Soal="Q1")
    long = pd.concat([long, long.assign(Soal="Q2", R1="other question")])
    assert importer.answers_from_table(long, "ID", ["First", "Last"], {"Q1": ("R1", ("Soal", "Q1"))}, "test") == \
        (rows, report)
    db.import_course_answers(course[0], rows)
    again, report = importer.answers_from_table(wide(), "ID", [], {"Q1": ("R1", None)}, "test")
    assert again == [] and report["existing"] == ["Q1_101", "Q1_102"]
    assert db.students(course[0]).external_id.tolist() == ["101", "102"]


def test_answer_table_errors(course):
    dup = pd.DataFrame({"ID": ["a b", "a b", "a/b"], "R": ["x", "y", "z"]})
    with pytest.raises(importer.ImportDataError, match="appears twice.*same answer id Q1_a-b"):
        importer.answers_from_table(dup, "ID", [], {"Q1": ("R", None)}, "test")
    with pytest.raises(importer.ImportDataError, match="no student id"):
        importer.answers_from_table(pd.DataFrame({"ID": [""], "R": ["x"]}), "ID", [], {"Q1": ("R", None)}, "test")


def test_scores_from_table(course):
    rows, _ = importer.answers_from_table(wide(), "ID", [], {"Q1": ("R1", None)}, "test")
    db.import_course_answers(course[0], rows)
    table = pd.DataFrame({"ID": ["101", "102", "103"], "Nilai": ["80", "72,5", ""], "K1": ["50", "", ""]})
    df = importer.scores_from_table(table, "ID", "Q1", {"_total": "Nilai", "K1_Bahan": "K1"}, "D1")
    assert df.values.tolist() == [["Q1_101", "D1", "_total", 80.0], ["Q1_101", "D1", "K1_Bahan", 50.0],
                                  ["Q1_102", "D1", "_total", 72.5]]
    with pytest.raises(importer.ImportDataError, match="outside 0-100.*not a number"):
        importer.scores_from_table(table.assign(Nilai=["120", "abc", ""]), "ID", "Q1", {"_total": "Nilai"}, "D1")
    with pytest.raises(importer.ImportDataError, match="'999' has no answer"):
        importer.scores_from_table(pd.DataFrame({"ID": ["999"], "N": ["1"]}), "ID", "Q1", {"_total": "N"}, "D1")
    with pytest.raises(importer.ImportDataError, match="unknown criteria"):
        importer.scores_from_table(table, "ID", "Q1", {"K9": "K1"}, "D1")


def test_save_question_creates_then_updates(course):
    q = db.question("Q1")
    rubric, gold_raw = {**q["rubric"], "question_id": "Q1C"}, {**q["gold"], "question_id": "Q1C"}
    importer.save_question("Q1C", "P", "R", rubric, gold_raw, assessment_id=course[1])
    before = len(kg.get_graph(kg.gold_graph_name("Q1C")))
    gold_raw = {**gold_raw, "triples": gold_raw["triples"][:-1]}
    importer.save_question("Q1C", "P2", "R", rubric, gold_raw)
    assert db.question("Q1C")["prompt"] == "P2" and len(db.question("Q1C")["gold"]["triples"]) == 4
    assert len(kg.get_graph(kg.gold_graph_name("Q1C"))) < before
    with pytest.raises(importer.ImportDataError, match="already exists"):
        importer.save_question("Q1C", "P", "R", rubric, gold_raw, assessment_id=course[1])
    with pytest.raises(importer.ImportDataError, match="unknown question Q1D"):
        importer.save_question("Q1D", "P", "R", {**rubric, "question_id": "Q1D"}, {**gold_raw, "question_id": "Q1D"})
    bad = {**gold_raw, "triples": [{**gold_raw["triples"][0], "o": "Bulan"}]}
    with pytest.raises(gold.GoldError, match="undeclared concept"):
        importer.save_question("Q1C", "P3", "R", rubric, bad)
    assert db.question("Q1C")["prompt"] == "P2"
