"""The answer page: score with the SPARQL check, every tab, review and corrections, unknown answers."""
import re

import pytest
from playwright.sync_api import expect

from ui_helpers import clean, grade_demo, tr

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def run(live_server):
    return f"assessment-{grade_demo(live_server)}"


def test_score_check_and_every_tab(page, live_server, run, errors):
    page.goto(f"{live_server}/jawaban.html?run={run}&answer=Q1_A08")
    expect(page.get_by_role("heading", level=1)).to_contain_text("ans:Q1_A08")
    expect(page.locator(".score-big").first).to_have_text("50.0")
    expect(page.locator("summary .check-ok")).to_be_visible()
    for tab, shown in [("tab_graph", "canvas"), ("tab_alignment", "svg"), ("tab_reasoning", "svg"),
                       ("tab_rdf", "details[open] pre"), ("tab_sparql", "textarea")]:
        page.get_by_role("tab", name=tr(f"jawaban.{tab}")).click()
        expect(page.locator(f"[role=tabpanel]:not([hidden]) {shown}").first).to_be_visible()
    page.get_by_role("button", name=tr("sparql.run")).click()
    expect(page.locator("[role=tabpanel]:not([hidden]) .results table")).to_contain_text("Q1_A08")
    assert clean(errors) == []


def test_correct_review_and_move_on(page, live_server, run, errors):
    page.goto(f"{live_server}/jawaban.html?run={run}&answer=Q1_A08")
    page.get_by_role("button", name=tr("review.mark")).click()
    expect(page.get_by_role("alert")).to_contain_text(tr("error.reviewer"))  # no reviewer name yet
    page.locator("#reviewer").fill("DS")
    page.locator("#reviewer").press("Tab")
    page.get_by_label(tr("review.status_for", ref="R2")).select_option("MATCHED")
    page.get_by_role("button", name=tr("review.save")).click()
    expect(page.get_by_role("alert")).to_contain_text("reason")  # the API's 422 names the empty reason
    page.get_by_label(tr("review.reason_for", ref="R2")).fill("dibaca ulang")
    page.get_by_role("button", name=tr("review.save")).click()
    expect(page.locator(".score-big").nth(1)).to_have_text("70.0")
    expect(page.locator("summary .check-ok")).to_be_visible()
    page.get_by_role("button", name=tr("review.mark")).click()
    expect(page.locator("#answer-status")).to_have_text(tr("status.ditinjau"))
    page.get_by_role("link", name=tr("review.next")).click()
    expect(page).to_have_url(re.compile(r"answer=Q1_A07"))  # flagged answers come first
    assert clean(errors, allow=("422",)) == []


def test_unknown_or_missing_answer(page, live_server, errors):
    page.goto(f"{live_server}/jawaban.html?run=ui&answer=Q1_A01")
    expect(page.get_by_role("alert")).to_contain_text(tr("error.not_found"))
    expect(page.get_by_role("link", name=tr("common.home"))).to_be_visible()
    page.goto(f"{live_server}/jawaban.html")
    expect(page.get_by_role("alert")).to_contain_text(tr("jawaban.missing"))
    assert clean(errors, allow=("404",)) == []
