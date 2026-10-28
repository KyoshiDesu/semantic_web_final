"""LLM client with an on-disk response cache. The LLM never produces a score that the system uses."""
import hashlib
import json
import os
import time

import httpx
from dotenv import load_dotenv

from autograde import io

# Anthropic server-side refusal fallback ("default" routes by refusal category).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """No credentials and no cached response: callers fall back (e.g. template feedback)."""


def cache_dir():
    return io.ROOT / "outputs" / "cache" / "llm"


def anthropic_backend(system, user, schema, cfg):
    load_dotenv(io.ROOT / ".env")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set (see .env.example)")
    import anthropic

    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg["effort"], "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable(f"authentication failed: {e.message}") from e
    except anthropic.APIStatusError as e:  # SDK already retried 429/5xx
        raise LLMError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"connection error: {e}") from e
    if resp.stop_reason == "refusal":
        raise LLMError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise LLMError("response truncated at max_tokens")
    return next(b.text for b in resp.content if b.type == "text")


def openrouter_backend(system, user, schema, cfg):
    return chat_backend(OPENROUTER_URL, "OPENROUTER_API_KEY", system, user, schema, cfg, temperature=0,
                        reasoning={"effort": cfg["effort"]},
                        provider={"require_parameters": True,  # skip providers that would ignore the schema
                                  "data_collection": "deny"})  # student answers never reach providers that store or train on prompts


def gemini_backend(system, user, schema, cfg):
    """Google AI Studio directly. Its free tier may use prompts to improve Google's products: demo data only."""
    # No temperature: Gemini 3.6+ ignores it and will reject it in a later release.
    return chat_backend(GEMINI_URL, "GEMINI_API_KEY", system, user, schema, cfg, reasoning_effort=cfg["effort"])


def chat_backend(url, key_var, system, user, schema, cfg, **extra):
    """One call to an OpenAI-style chat completions API; extra holds the provider's own fields."""
    load_dotenv(io.ROOT / ".env")
    key = os.environ.get(key_var)
    if not key:
        raise LLMUnavailable(f"{key_var} is not set (see .env.example)")
    body = {"model": cfg["model"], "max_tokens": cfg["max_tokens"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "reply", "strict": True, "schema": schema}},
            **extra}
    for attempt in range(3):  # first try + 2 retries on 429/5xx and network errors, as the Anthropic SDK does
        try:
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)
            if r.status_code not in RETRY_STATUS:
                break
            err = f"API error {r.status_code}: {r.text[:300]}"
        except httpx.TransportError as e:
            err = f"connection error: {e}"
        if attempt < 2:
            time.sleep(2 ** attempt)
    else:
        raise LLMError(err)
    if r.status_code == 401:
        raise LLMUnavailable(f"authentication failed: {r.text[:300]}")
    if r.status_code != 200:
        raise LLMError(f"API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "error" in data:  # a provider error can arrive with status 200
        raise LLMError(f"API error: {data['error'].get('message')}")
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise LLMError("response truncated at max_tokens")
    msg = choice["message"]
    if not msg.get("content"):  # null on a refusal or a safety filter; LLMError lets feedback use the template
        raise LLMError(f"no reply: {msg.get('refusal') or choice.get('finish_reason')}")
    return msg["content"]


BACKENDS = {"anthropic": anthropic_backend, "openrouter": openrouter_backend, "gemini": gemini_backend}


def complete_json(system, user, schema, *, backend=None, cfg=None, cache=None):
    """JSON dict for (system, user, schema), cached by a hash of the whole request."""
    cfg = cfg or io.load_config()["llm"]
    request = {"provider": cfg["provider"], "model": cfg["model"], "effort": cfg["effort"],
               "schema": schema, "system": system, "user": user}
    key = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = (cache or cache_dir()) / f"{key}.json"
    if path.exists():
        return io.load_json(path)["response"]
    backend = backend or BACKENDS[cfg["provider"]]
    for _ in range(3):  # first try + 2 retries on invalid JSON
        text = backend(system, user, schema, cfg)
        try:
            data = json.loads(text)
            break
        except json.JSONDecodeError:
            continue
    else:
        raise LLMError("invalid JSON after 3 attempts")
    io.save_json({"request": request, "response": data}, path)
    return data
