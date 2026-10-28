"""The questions page: list, the key with its graphs and Turtle, and grading one answer now."""
import re

import pytest
from playwright.sync_api import expect

from ui_helpers import clean, tr

pytestmark = pytest.mark.browser


def test_list_and_key(page, live_server, errors):
    page.goto(f"{live_server}/soal.html")
    page.get_by_role("link", name="Q1", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Q1")
    key = page.locator("#panel-kunci")
    expect(key.locator("svg")).to_be_visible()
    expect(key.locator("pre")).to_contain_text("ag:ReferenceTriple")
    expect(key).not_to_contain_text("<!--")  # the example comment in the prompt is stripped
    page.get_by_label(tr("soal.graph_view")).select_option("reified")
    expect(key.locator("svg")).to_contain_text("ag:hasSubject")
    assert clean(errors) == []


def test_grade_a_stored_and_a_pasted_answer(page, live_server, errors):
    page.goto(f"{live_server}/soal.html?id=Q1#jawaban")
    answers = page.locator("#panel-jawaban")
    answers.get_by_role("row").filter(has_text="Q1_A08").get_by_role("button", name=tr("soal.try")).click()
    expect(answers.locator(".score-big")).to_have_text("50.0")
    answers.get_by_label(tr("soal.paste")).fill("Tumbuhan menyerap air.")
    answers.get_by_role("button", name=tr("soal.try_pasted")).click()
    expect(answers.get_by_role("alert")).to_contain_text("ANTHROPIC_API_KEY")  # LLM mode without a key
    answers.get_by_role("row").filter(has_text="Q1_A08").get_by_role("button", name=tr("soal.try")).click()
    answers.get_by_role("link", name=tr("soal.open_result")).click()
    expect(page).to_have_url(re.compile(r"jawaban\.html\?run=ui&answer=Q1_A08"))
    assert clean(errors, allow=("400",)) == []
