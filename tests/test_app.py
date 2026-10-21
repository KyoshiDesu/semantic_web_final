"""Offline demo: gold-mode annotation + template feedback, no API key."""
import pytest
from streamlit.testing.v1 import AppTest

from autograde import io

pytestmark = pytest.mark.embeddings


def app():
    return AppTest.from_file(str(io.ROOT / "app" / "streamlit_app.py"), default_timeout=120)


def test_pages_render_and_grade_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = app().run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Nilai Jawaban").run()
    at.selectbox[0].set_value("Q1_A07 (sintetis)").run()
    at.button[0].click().run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Hitung ulang SPARQL" in text and "✓ sama" in text
    assert "templat" in text
    at.sidebar.radio[0].set_value("Evaluasi").run()
    assert not at.exception
