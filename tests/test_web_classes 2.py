"""The classes page: a new course and assessment, a question uploaded as files, answers and scores from a CSV."""
import re

import pytest
from playwright.sync_api import expect

from autograde import authoring, db
from ui_helpers import clean, tr

pytestmark = pytest.mark.browser


def test_course_question_upload_and_csv_import(page, live_server, errors, tmp_path):
    page.goto(f"{live_server}/kelas.html")
    page.get_by_label(tr("kelas.code")).fill("SW1")
    page.get_by_label(tr("kelas.name")).fill("Semantic Web")
    page.get_by_role("button", name=tr("kelas.add_course")).click()
    expect(page).to_have_url(re.compile(r"kelas\.html\?course=\d+"))
    page.get_by_label(tr("kelas.assessment_name")).fill("UTS")
    page.get_by_role("button", name=tr("kelas.add_assessment")).click()
    expect(page.get_by_role("link", name="UTS")).to_be_visible()

    q = db.question("Q1")
    files = authoring.question_files(q["prompt"], q["reference_answer"], {**q["rubric"], "question_id": "Q1W"},
                                     {**q["gold"], "question_id": "Q1W"})
    paths = []
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
        paths.append(str(tmp_path / name))
    page.get_by_label(tr("kelas.question_files")).set_input_files(paths)
    page.get_by_role("button", name=tr("kelas.upload")).click()
    expect(page.get_by_role("link", name="Q1W")).to_be_visible()

    answers = tmp_path / "lms.csv"
    answers.write_bytes("﻿nim;nama;jawaban\n2201;Ani;Tumbuhan memakai cahaya matahari.\n2202;Budi;-\n".encode("utf-8"))
    tab = page.locator("#panel-answers")
    tab.get_by_label(tr("import.file")).set_input_files(str(answers))
    tab.get_by_label(tr("import.id_col")).select_option("nim")
    tab.get_by_label("nama", exact=True).check()
    tab.get_by_label(tr("import.answer_col", q="Q1W")).select_option("jawaban")
    tab.get_by_role("button", name=tr("import.check")).click()
    expect(tab).to_contain_text(tr("import.check_result", new=1, blank=1, existing=0))
    tab.get_by_role("button", name=tr("import.run")).click()
    students = page.locator("section.panel").filter(has=page.get_by_role("heading", name=tr("kelas.students")))
    expect(students.get_by_role("cell", name="Ani", exact=True)).to_be_visible()  # the preview also shows Ani

    page.get_by_role("tab", name=tr("import.tab_scores")).click()
    scores = tmp_path / "scores.csv"
    scores.write_text('nim,total\n2201,"85,5"\n', encoding="utf-8")
    tab = page.locator("#panel-scores")
    tab.get_by_label(tr("import.file")).set_input_files(str(scores))
    tab.get_by_label(tr("import.id_col")).select_option("nim")
    tab.get_by_label(tr("import.total")).select_option("total")
    tab.get_by_role("button", name=tr("import.run")).click()
    expect(page.locator(".toast").filter(has_text=tr("import.scores_done", n=1))).to_be_visible()  # toasts stack
    assert clean(errors) == []
