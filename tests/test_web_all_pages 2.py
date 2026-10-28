"""Every page with every tab opened, in both languages: no console errors and no missing translations.
And HTML typed by a student shows as text wherever the answer appears."""
import json

import pytest
from playwright.sync_api import expect

from autograde import db, pipeline
from ui_helpers import HTTP, clean, grade_demo, tr

pytestmark = pytest.mark.browser
PAYLOAD = "<img src=x onerror=window.__xss=1>"


@pytest.fixture(scope="module")
def aid(live_server):
    return grade_demo(live_server)


def pages(base, aid):
    course = HTTP.get(f"{base}/api/assessments/{aid}/status").json()["course"]["id"]
    return ["index.html", f"kelas.html?course={course}", f"penilaian.html?id={aid}", "soal.html", "soal.html?id=Q1",
            "soal.html?new=1&copy=Q1", f"jawaban.html?run=assessment-{aid}&answer=Q1_A08", "ontologi.html",
            "graf.html?name=urn:ag:gold:Q1", f"jelajah.html?question=Q1&run=assessment-{aid}", "sparql.html",
            "evaluasi.html"]


def settled(page):
    expect(page.locator("main [role=status]")).to_have_count(0, timeout=30000)  # every "loading" placeholder replaced


@pytest.mark.parametrize("lang", ["id", "en"])
def test_every_page_and_tab_in_both_languages(page, live_server, aid, errors, lang):
    page.goto(f"{live_server}/")
    page.get_by_role("button", name=lang.upper(), exact=True).click()
    expect(page.locator("html")).to_have_attribute("lang", lang)
    for path in pages(live_server, aid):
        page.goto(f"{live_server}/{path}")
        settled(page)
        expect(page.get_by_role("navigation", name=tr("nav.label", lang))).to_be_visible()
        for tab in page.get_by_role("tab").all():
            tab.click()
            settled(page)
    assert clean(errors) == []


def test_student_html_stays_text(page, live_server, aid, errors):
    course = HTTP.get(f"{live_server}/api/assessments/{aid}/status").json()["course"]["id"]
    mapping = {"id_col": "nim", "name_cols": ["nama"], "columns": {"Q1": {"column": "jawaban"}}}
    csv = f"nim,nama,jawaban\n9001,{PAYLOAD},Tumbuhan {PAYLOAD} menyerap air.\n".encode("utf-8")
    r = HTTP.post(f"{live_server}/api/courses/{course}/answers", files={"file": ("lms.csv", csv)},
                  data={"mapping": json.dumps(mapping)})
    assert r.status_code == 200 and r.json()["added"] == 1
    ctx = pipeline.Context.load("Q1")
    text = db.answers(include_synthetic=True).set_index("answer_id").text["Q1_A08"]
    pipeline.run_answer(ctx, "Q1_A08", f"{text} {PAYLOAD}.", "gold", pipeline.ui_run(), use_llm_feedback=False)
    sentence = next(s for s, x in db.result("ui", "Q1_A08")["sentences"] if PAYLOAD in x)
    for path in ("index.html", f"penilaian.html?id={aid}", "soal.html?id=Q1#jawaban", "jawaban.html?run=ui&answer=Q1_A08"):
        page.goto(f"{live_server}/{path}")
        settled(page)
        expect(page.locator("main")).to_contain_text("<img src=x")
        assert page.locator("main img").count() == 0, path
    page.goto(f"{live_server}/jelajah.html?question=Q1&run=ui&answers=Q1_A08")
    expect(page.locator(".net canvas")).to_be_visible()
    page.evaluate(f"() => document.querySelector('.net').showDetails('ans:{sentence}')")
    expect(page.locator(".details")).to_contain_text("<img src=x")
    assert page.locator("main img").count() == 0
    assert page.evaluate("() => window.__xss") is None
    assert clean(errors) == []
