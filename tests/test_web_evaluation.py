"""The evaluation page: the runs, a report rendered from Markdown with its raw HTML shown as text, and figures."""
import base64

import pytest
from playwright.sync_api import expect

from autograde import db, evaluate
from ui_helpers import clean

pytestmark = pytest.mark.browser
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def test_report_figures_and_escaped_html(page, live_server, errors, monkeypatch, tmp_path):
    monkeypatch.setattr(evaluate, "report_dir", lambda run_id: tmp_path / run_id)
    db.create_run("r-web", "gold", "test", "all", {"tau_h": 0.8}, True, "sparql", False)
    db.finish_run("r-web")
    db.save_evaluation("r-web", "# Evaluasi\n\nICC = 0.9 <img src=x onerror=window.__md=1>")
    (tmp_path / "r-web").mkdir()
    (tmp_path / "r-web" / "scatter.png").write_bytes(PNG)
    page.goto(f"{live_server}/evaluasi.html")
    page.get_by_role("link", name="r-web").click()
    expect(page.locator(".report h1")).to_have_text("Evaluasi")
    expect(page.locator(".report")).to_contain_text("<img src=x onerror=window.__md=1>")
    assert page.locator(".report img").count() == 0
    expect(page.get_by_role("img", name="scatter.png")).to_be_visible()
    assert clean(errors) == []
