"""The ontology page (classes, properties, relations, SWRL rules, OWL file) and the named-graph browser."""
import pytest
from playwright.sync_api import expect

from ui_helpers import clean, tr

pytestmark = pytest.mark.browser


def test_ontology_tabs(page, live_server, errors):
    page.goto(f"{live_server}/ontologi.html")
    expect(page.locator("#panel-classes svg")).to_be_visible()
    page.get_by_role("tab", name=tr("ontologi.tab_rules")).click()
    expect(page.locator("#panel-rules h3")).to_have_count(3)
    page.get_by_role("tab", name=tr("ontologi.tab_relations")).click()
    page.get_by_label(tr("ontologi.lang_filter")).select_option("en")
    expect(page.locator("#panel-relations table")).to_contain_text("is_a")
    expect(page.locator("#panel-relations table")).not_to_contain_text("menggunakan")
    page.get_by_role("tab", name=tr("ontologi.tab_properties")).click()
    expect(page.locator("#panel-properties th").first).to_have_text(tr("col.property"))
    page.get_by_role("tab", name=tr("ontologi.tab_owl")).click()
    expect(page.locator("#panel-owl pre")).to_contain_text("<?xml")
    assert clean(errors) == []


def test_named_graphs(page, live_server, errors):
    page.goto(f"{live_server}/graf.html")
    page.get_by_role("link", name="urn:ag:gold:Q1", exact=True).click()
    expect(page.locator("#panel-turtle pre")).to_contain_text("ag:ReferenceTriple")
    page.get_by_role("tab", name=tr("graf.tab_view")).click()
    expect(page.locator("#panel-view canvas")).to_be_visible()
    page.get_by_role("tab", name=tr("graf.tab_triples")).click()
    expect(page.locator("#panel-triples tbody tr").first).to_be_visible()
    page.goto(f"{live_server}/graf.html?name=urn:ag:nope")
    expect(page.get_by_role("alert")).to_contain_text(tr("error.not_found"))
    assert clean(errors) == []
