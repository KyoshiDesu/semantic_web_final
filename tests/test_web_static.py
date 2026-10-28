"""The web folder without a browser: both languages complete, every key the pages name exists, vendored files
unchanged."""
import hashlib
import json
import re

from autograde import io

WEB = io.ROOT / "web"
VENDOR = {"vis-network.min.js": "f53f833ddb9bf97efe856bb0637d4fe88f39e39999c7e94a4b8afc8de8a1a2e5",
          "viz.js": "b9840ae5b70681356c207510db8820ac3f883607740616455d9c7c47d67ea646",
          "marked.esm.js": "930457e5d55439f90465015cc507d3323366e80df5f7a701b61189d4e1046bda"}


def flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        out.update(flat(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}": v})
    return out


def load(lang):
    return flat(json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8")))


def test_both_languages_have_the_same_keys_and_placeholders():
    ind, en = load("id"), load("en")
    assert sorted(ind) == sorted(en)
    for k in ind:
        assert isinstance(ind[k], str) and ind[k] and isinstance(en[k], str) and en[k], k
        assert sorted(re.findall(r"\{(\w+)\}", ind[k])) == sorted(re.findall(r"\{(\w+)\}", en[k])), k


def test_every_key_the_pages_name_exists():
    used = set()
    for p in WEB.glob("*.html"):
        used |= set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', p.read_text(encoding="utf-8")))
    for p in (WEB / "js").glob("*.js"):
        used |= set(re.findall(r'\bt\("([a-z_]+\.[^"]+)"', p.read_text(encoding="utf-8")))
    assert sorted(used - set(load("id"))) == []


def test_vendored_libraries_are_the_pinned_releases():
    for name, digest in VENDOR.items():
        assert hashlib.sha256((WEB / "vendor" / name).read_bytes()).hexdigest() == digest, name


def test_streamlit_is_gone():
    assert not (io.ROOT / "app").exists()
    assert "streamlit" not in (io.ROOT / "requirements.txt").read_text(encoding="utf-8")
