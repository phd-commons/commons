"""Wire format of the OpenAI-compatible and Anthropic providers, against a mock transport."""

from __future__ import annotations

import json

import httpx

from phd_commons.llm import Router, extract_json, strip_reasoning


def _router(ws, handler):
    r = Router(ws)
    r._http = httpx.Client(transport=httpx.MockTransport(handler))
    return r


def test_openai_compatible_chat_and_embed(ws, monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen[req.url.path] = (dict(req.headers), json.loads(req.content))
        if req.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "<think>hmm</think>ready"}}],
                                             "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
        body = json.loads(req.content)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2, 0.3]}
                                                  for i, _ in enumerate(body["input"])]})

    monkeypatch.setenv("TEST_KEY", "sk-test")
    ws.cfg["providers"]["srv"] = {"kind": "openai", "base_url": "http://127.0.0.1:9999/v1", "locality": "local",
                                  "api_key_env": "TEST_KEY"}
    ws.cfg["roles"]["author"] = {"provider": "srv", "model": "m-author"}
    ws.cfg["roles"]["embed"] = {"provider": "srv", "model": "m-embed"}
    r = _router(ws, handler)
    assert r.chat("author", [{"role": "user", "content": "hi"}], app="test") == "ready"
    hdrs, body = seen["/v1/chat/completions"]
    assert hdrs["authorization"] == "Bearer sk-test" and body["model"] == "m-author"
    v = r.embed(["a", "b"], app="test")
    assert v.shape == (2, 3)


def test_anthropic_messages(ws, monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen["h"], seen["b"] = dict(req.headers), json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ready"}],
                                         "usage": {"input_tokens": 3, "output_tokens": 1}})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    ws.cfg["providers"]["ant"] = {"kind": "anthropic", "locality": "cloud"}
    ws.cfg["roles"]["author"] = {"provider": "ant", "model": "claude-x"}
    ws.cfg["cloud"]["public"] = True
    r = _router(ws, handler)
    out = r.chat("author", [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}], app="t")
    assert out == "ready" and seen["b"]["system"] == "be brief" and seen["h"]["x-api-key"] == "k"
    assert all(m["role"] != "system" for m in seen["b"]["messages"])


def test_reply_cleaning():
    assert strip_reasoning("<think>a\nb</think>\nanswer") == "answer"
    assert extract_json('Sure! ```json\n[{"a": 1}]\n``` done') == [{"a": 1}]
    assert extract_json('prefix {"score": 2} suffix') == {"score": 2}


def test_thinking_off_and_empty_reply_retry(ws):
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ready"}, "finish_reason": "stop"}]})

    ws.cfg["providers"]["q"] = {"kind": "openai", "base_url": "http://127.0.0.1:9/v1", "locality": "local",
                                "thinking": "off"}
    ws.cfg["roles"]["worker"] = {"provider": "q", "model": "qwen"}
    r = _router(ws, handler)
    assert r.chat("worker", [{"role": "user", "content": "hi"}], app="t", max_tokens=50) == "ready"
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert calls[0]["messages"][0]["content"].startswith("/no_think")
    assert calls[1]["max_tokens"] == 200
