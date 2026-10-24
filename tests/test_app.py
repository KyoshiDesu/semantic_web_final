"""Offline demo: every page renders; grading with annotations + template feedback; SPARQL console. No API key."""
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from autograde import db, importer, io

pytestmark = pytest.mark.embeddings


@pytest.fixture
def at(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(str(io.ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    assert not at.exception, at.exception
    return at


def page(at, url_path):
    at._page_hash = calc_hash(url_path)  # shortcut: AppTest.switch_page only knows page files, not st.Page(callable)
    at.run()
    assert not at.exception, at.exception


def grade(at, qid, answer_prefix):
    at.selectbox[0].set_value(qid).run()
    answer = next(o for o in at.selectbox[1].options if o.startswith(answer_prefix))
    at.selectbox[1].set_value(answer).run()
    at.button[0].click().run()
    assert not at.exception, at.exception


def test_static_pages(at):
    for name in ["ontology", "question", "explorer", "sparql", "evaluation", "kg", "mata-kuliah", "editor", "impor"]:
        page(at, name)
        assert at.header or at.selectbox or at.info, name  # the page body rendered


def test_grade_q1_and_sparql(at):
    grade(at, "Q1", "Q1_A07")
    assert any("✓ sama" in str(m.delta) for m in at.metric)
    at.button(key="run_ans").click().run()  # first preset: score recompute
    assert not at.exception, at.exception
    assert at.dataframe[-1].value.iloc[0]["score"] == pytest.approx(next(
        float(m.value) for m in at.metric if m.label == "Skor sistem"))


def test_grade_contradiction(at):
    grade(at, "Q1", "Q1_A08")
    assert next(m.value for m in at.metric if m.label == "Skor sistem") == "50.0"
    assert any("ag:contradicts" in c.value for c in at.code)


class Upload:
    """Stands in for st.file_uploader's UploadedFile (AppTest cannot drive the uploader)."""

    def __init__(self, name, text):
        self.name, self.data = name, text.encode("utf-8")

    def getvalue(self):
        return self.data


def test_course_setup_and_lms_import(fresh_db, monkeypatch):
    importer.import_files()
    at = AppTest.from_file(str(io.ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    page(at, "mata-kuliah")
    at.text_input[0].set_value("BIO1")
    at.text_input[1].set_value("Biologi")
    at.button[0].click().run()
    at.text_input[2].set_value("UTS")
    at.button[1].click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    course = next(c["id"] for c in db.courses() if c["code"] == "BIO1")
    assessment = db.assessments(course)[0]["id"]

    q1 = io.ROOT / "data" / "questions" / "Q1"
    files = [Upload(f, (q1 / f).read_text(encoding="utf-8").replace("question_id: Q1", "question_id: Q1B"))
             for f in importer.QUESTION_FILES]
    csv = "NIM;Nama;Jawaban Q1B\n101;Ani;Tumbuhan menyerap cahaya.\n102;Budi;-\n"
    uploads = {"question_files": files, "answers_csv": Upload("lms.csv", csv)}
    monkeypatch.setattr("streamlit.file_uploader", lambda *a, key=None, **k: uploads.get(key))
    page(at, "mata-kuliah")
    at.selectbox(key="courses_course").set_value(course)
    at.selectbox(key="upload_assessment").set_value(assessment)
    at.button[-1].click().run()  # Tambah soal
    assert not at.error, [e.value for e in at.error]
    assert db.questions(assessment) == ["Q1B"]

    page(at, "impor")
    at.selectbox(key="import_course").set_value(course).run()
    at.selectbox(key="ans_id").set_value("NIM")
    at.multiselect(key="ans_name").set_value(["Nama"])
    at.selectbox(key="ans_col_Q1B").set_value("Jawaban Q1B").run()
    assert not at.error, [e.value for e in at.error]
    at.button(key="ans_import").click().run()
    assert not at.error, [e.value for e in at.error]
    assert db.students(course).values.tolist() == [["101", "Ani", 1]]
    assert db.answers().answer_id.tolist() == ["Q1B_101"]


def test_question_editor_create_and_edit(fresh_db):
    from autograde import authoring
    from autograde.models import Feedback, ScoreResult
    importer.import_files()
    at = AppTest.from_file(str(io.ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    page(at, "editor")
    assert not at.warning  # Q1 has no graded results yet
    at.radio(key="ed_mode").set_value("Soal baru").run()
    at.text_input(key="ed_new_id").set_value("Q1E")
    at.selectbox(key="ed_copy").set_value("Q1").run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert any("urn:ag:gold:Q1E" in c.value for c in at.caption)  # preview of the future named graph
    draft = at.session_state["ed_draft"]
    draft["criteria"].loc[0, "description"] = "Bahan baku"
    at.session_state["ed_draft"] = draft
    at.button(key="ed_save").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert db.question("Q1E")["rubric"]["criteria"][0]["description"] == "Bahan baku"
    assert at.selectbox(key="ed_qid").value == "Q1E"  # switched to editing the new question

    # a broken key blocks saving
    draft = at.session_state["ed_draft"]
    draft["triples"].loc[0, "o"] = None
    at.session_state["ed_draft"] = draft
    at.run()
    assert at.error and at.button(key="ed_save").disabled

    sc = ScoreResult(answer_id="Q1_A07", score=1, sum_weighted_credit=0, sum_penalty=0, sum_weights=1, params={},
                     sparql_score=1)
    db.create_run("r1", "gold", "all", "Q1", {}, False, "pellet", True)
    db.save_result("r1", "Q1", "Q1_A07", {"sentences": [], "students": [], "entries": [], "score": sc, "log": [],
                                          "feedback": Feedback(answer_id="Q1_A07", claims=[], summary=""),
                                          "trace": {"sigmas": {}, "aligned": [], "contradictions": []}})
    at.selectbox(key="ed_qid").set_value("Q1").run()
    assert any("1 hasil penilaian" in w.value for w in at.warning)
    assert authoring.to_tables(db.question("Q1"))["criteria"].description[0] != "Bahan baku"
