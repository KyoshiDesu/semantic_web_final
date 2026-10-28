"""The home page: the pieces link to where they are visible, search and filters, cards that lead to the answer."""
import re

import pytest
from playwright.sync_api import expect

from ui_helpers import clean, grade_demo, tr

pytestmark = pytest.mark.browser


def test_cards_filters_and_search(page, live_server, errors):
    page.goto(f"{live_server}/")
    expect(page.locator(".card")).to_have_count(7)
    expect(page.locator(".card").first).to_contain_text(tr("status.belum dinilai"))
    grade_demo(live_server)
    page.reload()
    contradiction = page.get_by_role("button", name=tr("search.filter_contradiction"))
    contradiction.click()
    expect(page.locator(".card")).to_have_count(2)
    a08 = page.locator(".card").filter(has_text="ans:Q1_A08")
    expect(a08).to_contain_text("⟂ ag:contradicts key:Q1_R2")
    contradiction.click()
    expect(page.locator(".card")).to_have_count(7)
    page.get_by_label(tr("search.label")).fill("glukosa oksigen dilepaskan")
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card")).to_contain_text("ans:Q1_S01")
    page.get_by_label(tr("search.label")).fill("")
    contradiction.click()
    a08.get_by_role("link", name=tr("search.explore")).click()
    expect(page).to_have_url(re.compile(r"jawaban\.html\?run=assessment-\d+&answer=Q1_A08"))
    assert clean(errors) == []


def test_pieces_and_templates_link_to_their_pages(page, live_server):
    page.goto(f"{live_server}/")
    expect(page.get_by_role("link", name=tr("home.piece_owl"))).to_have_attribute("href", "ontologi.html")
    expect(page.get_by_role("link", name=tr("home.piece_skos"))).to_have_attribute("href", "soal.html?id=Q1#kunci")
    expect(page.get_by_role("link", name="Jumlah triple per named graph")).to_have_attribute(
        "href", re.compile(r"^sparql\.html\?template="))
