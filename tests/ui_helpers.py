"""Helpers for the browser tests: the UI text of a key, grading the demo through the API, console checks."""
import json
import time

import httpx

from autograde import io

HTTP = httpx.Client(trust_env=False, timeout=60)  # never route 127.0.0.1 through a proxy from the environment
I18N = {lang: json.loads((io.ROOT / "web" / "i18n" / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("id", "en")}


def tr(key, lang="id", **values):
    """The text a page shows for a translation key."""
    text = I18N[lang]
    for part in key.split("."):
        text = text[part]
    return text.format(**values) if values else text


def demo_assessment(base):
    course = next(c for c in HTTP.get(f"{base}/api/courses").json() if c["code"] == "DEMO")["id"]
    return HTTP.get(f"{base}/api/courses/{course}/assessments").json()[0]["id"]


def grade_demo(base):
    """Grade the demo assessment's ungraded answers and wait for the job; returns the assessment id."""
    aid = demo_assessment(base)
    r = HTTP.post(f"{base}/api/assessments/{aid}/grading", json={"which": "new"})
    if r.status_code == 422:  # nothing left to grade
        return aid
    job_id, deadline = r.json()["id"], time.monotonic() + 120
    while HTTP.get(f"{base}/api/jobs/{job_id}").json()["status"] == "running":
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} did not finish")
        time.sleep(0.1)
    return aid


def clean(errors, allow=()):
    """The console problems a test collected, minus the ones it provoked on purpose and aborted navigations."""
    return [e for e in errors if "net::ERR_ABORTED" not in e and not any(a in e for a in allow)]
