"""The assessment page: grading with live progress, a reload during grading, bulk review, gated exports."""
import threading

import pytest
from playwright.sync_api import expect

from autograde import db, pipeline
from ui_helpers import HTTP, clean, demo_assessment, tr

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def aid(live_server):
    return demo_assessment(live_server)


def test_grade_review_and_export(page, live_server, aid, errors):
    page.goto(f"{live_server}/penilaian.html?id={aid}")
    expect(page.get_by_role("heading", level=1)).to_contain_text("DEMO")
    page.get_by_role("button", name=tr("penilaian.grade_new", n=7)).click()
    expect(page.locator("#job-area progress")).to_be_visible()
    expect(page.locator(".counts")).to_contain_text(f"7 {tr('status.dinilai')}", timeout=60000)
    page.locator("#reviewer").fill("DS")
    page.locator("#reviewer").press("Tab")
    page.get_by_role("button", name=tr("penilaian.approve", n=4)).click()
    expect(page.locator(".counts")).to_contain_text(f"4 {tr('status.ditinjau')}")
    expect(page.get_by_role("button", name=tr("penilaian.final_grades"))).to_be_disabled()
    with page.expect_download() as download:
        page.get_by_role("link", name=tr("penilaian.draft_grades")).click()
    assert download.value.path().read_text(encoding="utf-8-sig").startswith("# DRAF")
    for answer in ("Q1_A07", "Q1_A08", "Q1_S03"):  # the flagged ones, reviewed one by one on their pages
        HTTP.post(f"{live_server}/api/results/assessment-{aid}/{answer}/review", json={"by": "DS"})
    page.reload()
    with page.expect_download() as download:
        page.get_by_role("link", name=tr("penilaian.final_grades")).click()
    assert download.value.path().read_text(encoding="utf-8-sig").startswith("external_id,name,Q1")
    assert clean(errors) == []


def test_reload_during_grading_follows_the_same_job(page, live_server, aid, errors, monkeypatch):
    gate, orig = threading.Event(), pipeline.grade_assessment_answer

    def held(*args, **kwargs):
        gate.wait(30)
        return orig(*args, **kwargs)

    monkeypatch.setattr(pipeline, "grade_assessment_answer", held)
    q = db.question("Q1")
    db.update_question("Q1", q["prompt"], q["reference_answer"], q["rubric"], q["gold"])  # every answer goes stale
    page.goto(f"{live_server}/penilaian.html?id={aid}")
    page.get_by_role("button", name=tr("penilaian.grade_stale", n=7)).click()
    expect(page.locator("#job-area progress")).to_be_visible()
    job = HTTP.get(f"{live_server}/api/assessments/{aid}/status").json()["job"]
    page.reload()
    expect(page.locator("#job-area progress")).to_be_visible()
    expect(page.get_by_role("button", name=tr("penilaian.grade_stale", n=7))).to_have_count(0)  # no second start
    gate.set()
    expect(page.locator(".counts")).to_contain_text(f"7 {tr('status.dinilai')}", timeout=60000)
    assert HTTP.get(f"{live_server}/api/assessments/{aid}/status").json()["job"]["id"] == job["id"]
    assert clean(errors) == []


def test_unknown_assessment(page, live_server, errors):
    page.goto(f"{live_server}/penilaian.html?id=999")
    expect(page.get_by_role("alert")).to_contain_text(tr("error.not_found"))
    assert clean(errors, allow=("404",)) == []
