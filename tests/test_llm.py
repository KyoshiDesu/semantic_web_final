import httpx
import pytest

from autograde import llm

CFG = {"provider": "anthropic", "model": "m1", "effort": "medium", "max_tokens": 100}
SCHEMA = {"type": "object"}


def test_cache_hit_skips_backend(tmp_path):
    calls = []
    backend = lambda *a: calls.append(1) or '{"x": 1}'
    assert llm.complete_json("s", "u", SCHEMA, backend=backend, cfg=CFG, cache=tmp_path) == {"x": 1}
    assert llm.complete_json("s", "u", SCHEMA, backend=backend, cfg=CFG, cache=tmp_path) == {"x": 1}
    assert len(calls) == 1


def test_cache_key_includes_model(tmp_path):
    calls = []
    backend = lambda *a: calls.append(1) or "{}"
    llm.complete_json("s", "u", SCHEMA, backend=backend, cfg=CFG, cache=tmp_path)
    llm.complete_json("s", "u", SCHEMA, backend=backend, cfg={**CFG, "model": "m2"}, cache=tmp_path)
    assert len(calls) == 2


def test_retries_invalid_json(tmp_path):
    replies = iter(["not json", "{bad", '{"ok": true}'])
    assert llm.complete_json("s", "u", SCHEMA, backend=lambda *a: next(replies), cfg=CFG, cache=tmp_path) == {"ok": True}


def test_gives_up_after_two_retries(tmp_path):
    with pytest.raises(llm.LLMError):
        llm.complete_json("s", "u", SCHEMA, backend=lambda *a: "nope", cfg=CFG, cache=tmp_path)


def test_no_key_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(llm.io, "ROOT", tmp_path)  # no .env here
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(llm.LLMUnavailable):
        llm.anthropic_backend("s", "u", SCHEMA, CFG)


def test_openrouter_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(llm.io, "ROOT", tmp_path)  # no .env here
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMUnavailable):
        llm.openrouter_backend("s", "u", SCHEMA, CFG)

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    ok = {"choices": [{"finish_reason": "stop", "message": {"content": '{"x": 1}'}}]}
    replies, sent = [httpx.Response(503, text="busy"), httpx.Response(200, json=ok)], []
    monkeypatch.setattr(llm.httpx, "post", lambda url, json, **k: sent.append(json) or replies.pop(0))
    assert llm.openrouter_backend("s", "u", SCHEMA, CFG) == '{"x": 1}'
    assert len(sent) == 2 and sent[0]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert sent[0]["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert sent[0]["provider"]["data_collection"] == "deny"

    blocked = {"choices": [{"finish_reason": "content_filter", "message": {"content": None}}]}
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: httpx.Response(200, json=blocked))
    with pytest.raises(llm.LLMError, match="content_filter"):
        llm.openrouter_backend("s", "u", SCHEMA, CFG)

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: httpx.Response(401, text="bad key"))
    with pytest.raises(llm.LLMUnavailable, match="bad key"):
        llm.openrouter_backend("s", "u", SCHEMA, CFG)
