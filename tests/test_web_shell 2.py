"""The shared page shell in a real browser: nav, language switch, CSP, and the API client's retry and errors."""
import pytest
from playwright.sync_api import expect

from ui_helpers import clean, tr

pytestmark = pytest.mark.browser


def test_home_shell_loads_clean(page, live_server, errors):
    page.goto(f"{live_server}/")
    expect(page.get_by_role("heading", level=1)).to_have_text(tr("home.title"))
    nav = page.get_by_role("navigation", name=tr("nav.label"))
    expect(nav.get_by_role("link", name=tr("nav.home"), exact=True)).to_have_attribute("aria-current", "page")
    expect(page).to_have_title(f"{tr('nav.home')} · AutoGrade-RDF")
    assert clean(errors) == []


def test_language_switch_persists(page, live_server, errors):
    page.goto(f"{live_server}/")
    page.get_by_role("button", name="EN", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text(tr("home.title", "en"))
    page.goto(f"{live_server}/index.html")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    page.get_by_role("button", name="ID", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text(tr("home.title"))
    assert clean(errors) == []


def test_inline_scripts_are_blocked(page, live_server):
    page.goto(f"{live_server}/")
    page.evaluate("() => { const s = document.createElement('script'); s.textContent = 'window.__inline = 1';"
                  " document.body.append(s); }")
    assert page.evaluate("() => window.__inline") is None


def test_get_retries_a_busy_store_but_post_does_not(page, live_server):
    page.goto(f"{live_server}/")
    calls = {"GET": 0, "POST": 0}

    def busy_once(route):
        calls[route.request.method] += 1
        if calls[route.request.method] == 1:
            route.fulfill(status=503, headers={"Retry-After": "0"},
                          json={"error": "busy", "message": "in use", "details": []})
        else:
            route.continue_()

    page.route("**/api/courses", busy_once)
    courses = page.evaluate("async () => (await import('/js/api.js')).api.get('/courses')")
    assert calls["GET"] == 2 and courses[0]["code"] == "DEMO"
    err = page.evaluate("""async () => { const { api } = await import('/js/api.js');
        try { await api.post('/courses', { code: 'X9', name: 'x' }); return null; }
        catch (e) { return { status: e.status, code: e.code }; } }""")
    assert err == {"status": 503, "code": "busy"} and calls["POST"] == 1


def test_api_errors_carry_the_error_body(page, live_server):
    page.goto(f"{live_server}/")
    err = page.evaluate("""async () => { const { api } = await import('/js/api.js');
        try { await api.get('/courses/999/assessments'); } catch (e) { return [e.code, e.message, e.details]; } }""")
    assert err == ["not_found", "unknown course 999", []]
