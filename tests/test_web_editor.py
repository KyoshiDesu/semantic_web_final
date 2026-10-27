"""The question editor: live preview, an invalid draft blocks saving, saving marks graded answers stale, copy as new."""
import re

import pytest
from playwright.sync_api import expect

from ui_helpers import HTTP, clean, grade_demo, tr

pytestmark = pytest.mark.browser


def test_preview_invalid_then_save_marks_answers_stale(page, live_server, errors):
    aid = grade_demo(live_server)
    page.goto(f"{live_server}/soal.html?id=Q1#editor")
    editor = page.locator("#panel-editor")
    expect(editor.get_by_text(tr("editor.valid"))).to_be_visible()
    expect(editor.locator("svg")).to_be_visible()
    save = editor.get_by_role("button", name=tr("editor.save"))
    expect(save).to_be_enabled()
    editor.get_by_role("button", name=tr("editor.remove_row", n=3)).first.click()  # K3_Energi, which R1 still uses
    expect(editor.get_by_role("alert")).to_contain_text(tr("editor.not_valid"))
    expect(save).to_be_disabled()
    page.reload()
    editor.get_by_label(tr("soal.prompt")).fill("Jelaskan fotosintesis secara singkat.")
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator(".toast")).to_contain_text("Q1")
    assert HTTP.get(f"{live_server}/api/assessments/{aid}/status").json()["counts"] == {"usang": 7}
    assert clean(errors) == []


def test_copy_as_a_new_question(page, live_server, errors):
    page.goto(f"{live_server}/soal.html?id=Q1")
    page.get_by_role("link", name=tr("editor.copy")).click()
    page.get_by_label(tr("editor.new_id")).fill("Q1C")
    expect(page.get_by_text(tr("editor.valid"))).to_be_visible()
    page.get_by_role("button", name=tr("editor.save")).click()
    expect(page).to_have_url(re.compile(r"soal\.html\?id=Q1C"))
    expect(page.get_by_role("heading", level=1)).to_have_text("Q1C")
    assert clean(errors) == []
