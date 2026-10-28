"""The graph explorer (legend toggles, node details) and the SPARQL console page (templates, scopes, errors)."""
import pytest
from playwright.sync_api import expect

from ui_helpers import clean, grade_demo, tr

pytestmark = pytest.mark.browser
VISIBLE = "() => document.querySelector('.net').network.body.data.nodes.get({ filter: n => !n.hidden }).length"


def test_explorer_toggle_and_details(page, live_server, errors):
    aid = grade_demo(live_server)
    page.goto(f"{live_server}/jelajah.html?question=Q1&run=assessment-{aid}&answers=Q1_A08")
    expect(page.locator(".net canvas")).to_be_visible()
    before = page.evaluate(VISIBLE)
    page.get_by_role("button", name=tr("node.concept"), exact=True).click()
    assert page.evaluate(VISIBLE) < before
    page.evaluate("() => document.querySelector('.net').showDetails('ans:Q1_A08')")
    expect(page.locator(".details h3")).to_have_text("ans:Q1_A08")
    assert clean(errors) == []


def test_sparql_console_templates_scopes_and_errors(page, live_server, errors):
    page.goto(f"{live_server}/sparql.html")
    page.get_by_role("button", name=tr("sparql.run")).click()
    expect(page.locator(".results table")).to_contain_text("urn:ag:gold:Q1")  # triples per named graph
    page.get_by_label(tr("sparql.query")).fill("SELEKT ?x WHERE {")
    page.get_by_label(tr("sparql.query")).press("Control+Enter")
    expect(page.get_by_role("alert")).to_contain_text("query failed")
    page.goto(f"{live_server}/sparql.html?graphs=urn:ag:gold:Q1")
    page.get_by_label(tr("sparql.template")).select_option("Hierarki konsep (skos:broader+)")
    page.get_by_role("button", name=tr("sparql.run")).click()
    expect(page.locator(".results table")).to_contain_text("key:Glukosa")
    assert clean(errors, allow=("422",)) == []
