"""db import: Q1 + synthetic data into both stores; refuses to overwrite; validates before touching anything."""
import shutil

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
