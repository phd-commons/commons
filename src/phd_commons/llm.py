"""Bring your own LLM.

Models are resolved by role (author, worker, verifier, embed, rerank), never by name in application code.
Each role points at a provider declared in commons.yaml. Supported provider kinds:

  openai                 Any OpenAI-compatible server: Ollama, LM Studio, llama.cpp server, vLLM, mlx_lm.server,
                         a university AI gateway, OpenRouter, OpenAI itself, and other hosted APIs with a
                         compatible endpoint. Chat and embeddings.
  anthropic              Anthropic's Messages API. Chat only.
  sentence-transformers  In-process local embeddings and cross-encoder reranking (pip extra: local-embed).
  fake                   Deterministic offline stand-in for tests and demos. Not a model.

Every provider declares a locality: local, institutional or cloud. The router refuses to send content to a
provider whose locality is not allowed for the most sensitive tier in the request:

  local          everything
  institutional  PUBLIC and PRIVATE; RESTRICTED only if the provider names an ethics approval in
                 `restricted_approval` (for example an approved university-hosted service)
  cloud          PUBLIC only if cloud.public is true, PRIVATE only if cloud.private is true, RESTRICTED never

A role may name a `local_fallback` used when its main provider is not allowed for the tier at hand, so a
laptop user can send public literature to a hosted model and keep interview data on a small local one.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import numpy as np

TIER_RANK = {"PUBLIC": 0, "PRIVATE": 1, "RESTRICTED": 2}


class TierViolation(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


def max_tier(tiers) -> str:
    tiers = [t for t in tiers if t] or ["PUBLIC"]
    return max(tiers, key=lambda t: TIER_RANK.get(t, 2))


def strip_reasoning(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    if "<think>" in text.lower():  # unclosed block: drop everything before the answer marker, if any
        text = re.split(r"</?think>", text, flags=re.I)[-1]
    return text.strip()


def extract_json(text: str):
    """Tolerant JSON extraction from a model reply (fenced, prefixed or trailing prose)."""
    text = strip_reasoning(text)
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, flags=re.S)
    if fence:
        text = fence.group(1)
    pairs = [(text.find(o), o, c) for o, c in (("[", "]"), ("{", "}")) if text.find(o) != -1]
    for start, _, closer in sorted(pairs):  # whichever structure opens first is the reply
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model reply")


def host_is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Target:
    role: str
    provider_name: str
    provider: dict
    model: str


class Router:
    def __init__(self, ws, store=None):
        self.ws = ws
        self.store = store
        self.providers: dict = ws.cfg.get("providers", {})
        self.roles: dict = ws.cfg.get("roles", {})
        self._st_models: dict = {}
        self._http = httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0))

    # ---------- policy
    def effective_locality(self, provider: dict) -> str:
        """The declared locality, downgraded to cloud when the declaration cannot be true."""
        loc = provider.get("locality", "cloud")
        kind = provider.get("kind")
        if loc == "local":
            if kind == "anthropic":
                return "cloud"
            if kind == "openai" and not host_is_local(provider.get("base_url", "")):
                return "cloud"
        return loc

    def allowed(self, provider: dict, tier: str) -> bool:
        loc = self.effective_locality(provider)
        if loc == "local":
            return True
        if loc == "institutional":
            return tier != "RESTRICTED" or bool(provider.get("restricted_approval"))
        if tier == "PUBLIC":
            return bool(self.ws.get("cloud.public", False))
        if tier == "PRIVATE":
            return bool(self.ws.get("cloud.private", False))
        return False

    def resolve(self, role: str, tier: str = "PUBLIC") -> Target:
        spec = self.roles.get(role)
        if not spec:
            raise ProviderError(f"Role '{role}' is not configured in commons.yaml")
        candidates = [spec]
        if spec.get("local_fallback"):
            candidates.append(spec["local_fallback"])
        for cand in candidates:
            pname = cand.get("provider")
            prov = self.providers.get(pname)
            if prov is None:
                raise ProviderError(f"Role '{role}' points at unknown provider '{pname}'")
            if self.allowed(prov, tier):
                return Target(role, pname, prov, cand.get("model", ""))
        raise TierViolation(
            f"No provider for role '{role}' may receive {tier} material. Configure a local provider "
            f"(or a local_fallback) for this role, or change the cloud settings deliberately."
        )

    def can(self, role: str, tier: str) -> bool:
        try:
            self.resolve(role, tier)
            return True
        except (TierViolation, ProviderError):
            return False

    def describe(self) -> list[dict]:
        out = []
        for role, spec in self.roles.items():
            prov = self.providers.get(spec.get("provider"), {})
            out.append({
                "role": role, "provider": spec.get("provider"), "kind": prov.get("kind"),
                "model": spec.get("model"), "locality": self.effective_locality(prov),
                "family": spec.get("family", ""),
                "fallback": (spec.get("local_fallback") or {}).get("model", ""),
            })
        return out

    # ---------- audit
    def _audit(self, t: Target, app: str, tier: str, prompt: str, source_ids, tin, tout, ms, ok):
        if self.store is None:
            return
        self.store.log_call(
            app=app, role=t.role, provider=t.provider_name, model=t.model,
            locality=self.effective_locality(t.provider), max_tier=tier,
            prompt_sha=hashlib.sha256(prompt.encode("utf-8", "ignore")).hexdigest()[:16],
            source_ids_json=json.dumps(list(source_ids or [])), tokens_in=tin, tokens_out=tout, ms=ms, ok=int(ok),
        )

    # ---------- chat
    def chat(self, role: str, messages: list[dict], app: str, tier: str = "PUBLIC", source_ids=None,
             temperature: float = 0.2, max_tokens: int = 2048, json_mode: bool = False) -> str:
        if not app:
            raise ValueError("app tag is mandatory on every model call")
        t = self.resolve(role, tier)
        kind = t.provider.get("kind")
        prompt = json.dumps(messages, ensure_ascii=False)
        start = time.time()
        ok, tin, tout, text = False, None, None, ""
        try:
            if kind == "openai":
                text, tin, tout = self._openai_chat(t, messages, temperature, max_tokens, json_mode)
            elif kind == "anthropic":
                text, tin, tout = self._anthropic_chat(t, messages, temperature, max_tokens)
            elif kind == "fake":
                from .fake import fake_chat
                text = fake_chat(app, messages)
            else:
                raise ProviderError(f"Provider kind '{kind}' cannot chat")
            ok = True
            return strip_reasoning(text)
        finally:
            self._audit(t, app, tier, prompt, source_ids, tin, tout, int((time.time() - start) * 1000), ok)

    def _headers(self, prov: dict) -> dict:
        h = {"Content-Type": "application/json"}
        key_env = prov.get("api_key_env")
        if key_env:
            key = os.environ.get(key_env, "")
            if not key:
                raise ProviderError(f"Environment variable {key_env} is not set")
            h["Authorization"] = f"Bearer {key}"
        h.update(prov.get("headers", {}) or {})
        return h

    def _post(self, url: str, headers: dict, body: dict, retries: int = 3) -> dict:
        last = None
        for attempt in range(retries):
            try:
                r = self._http.post(url, headers=headers, json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise ProviderError(f"{r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ProviderError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise ProviderError(f"Request to {url} failed after {retries} attempts: {last}")

    @staticmethod
    def _thinking_off(provider: dict, messages: list[dict]) -> tuple[list[dict], dict]:
        """Ask a reasoning model to answer directly. Servers that do not know these hints ignore them."""
        if str(provider.get("thinking", "")).lower() not in ("off", "false", "no"):
            return messages, {}
        msgs = [dict(m) for m in messages]
        if msgs and msgs[0]["role"] == "system":
            if not msgs[0]["content"].startswith("/no_think"):
                msgs[0]["content"] = "/no_think\n" + msgs[0]["content"]
        else:
            msgs.insert(0, {"role": "system", "content": "/no_think"})
        return msgs, {"chat_template_kwargs": {"enable_thinking": False}}

    def _openai_chat(self, t: Target, messages, temperature, max_tokens, json_mode):
        base = t.provider["base_url"].rstrip("/")
        messages, extra = self._thinking_off(t.provider, messages)
        tin = tout = 0
        for attempt in range(2):
            body = {"model": t.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
            body.update(extra)
            body.update(t.provider.get("extra_body", {}) or {})
            if json_mode and t.provider.get("json_mode", False):
                body["response_format"] = {"type": "json_object"}
            data = self._post(f"{base}/chat/completions", self._headers(t.provider), body)
            choice = data["choices"][0]
            content = (choice.get("message") or {}).get("content") or ""
            usage = data.get("usage") or {}
            tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
            # A reasoning model can spend the whole budget thinking and return nothing: give it room once.
            if strip_reasoning(content) or choice.get("finish_reason") != "length" or max_tokens >= 8192:
                return content, tin, tout
            max_tokens = min(max_tokens * 4, 8192)
        return content, tin, tout

    def _anthropic_chat(self, t: Target, messages, temperature, max_tokens):
        key = os.environ.get(t.provider.get("api_key_env", "ANTHROPIC_API_KEY"), "")
        if not key:
            raise ProviderError("Anthropic API key environment variable is not set")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        body = {"model": t.model, "max_tokens": max_tokens, "temperature": temperature, "messages": rest}
        if system:
            body["system"] = system
        base = t.provider.get("base_url", "https://api.anthropic.com").rstrip("/")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data = self._post(f"{base}/v1/messages", headers, body)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return text, usage.get("input_tokens"), usage.get("output_tokens")

    # ---------- embeddings
    def embed_model_id(self, tier: str = "PUBLIC") -> str:
        t = self.resolve("embed", tier)
        return f"{t.provider_name}:{t.model}"

    def embed(self, texts: list[str], app: str, tier: str = "PUBLIC") -> np.ndarray:
        t = self.resolve("embed", tier)
        kind = t.provider.get("kind")
        start = time.time()
        ok = False
        try:
            if kind == "fake":
                from .fake import fake_embed
                out = fake_embed(texts)
            elif kind == "sentence-transformers":
                out = self._st(t.model).encode(texts, normalize_embeddings=True, convert_to_numpy=True)
            elif kind == "openai":
                base = t.provider["base_url"].rstrip("/")
                vecs = []
                for i in range(0, len(texts), 32):
                    data = self._post(f"{base}/embeddings", self._headers(t.provider),
                                      {"model": t.model, "input": texts[i:i + 32]})
                    vecs += [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
                out = np.array(vecs, dtype=np.float32)
            else:
                raise ProviderError(f"Provider kind '{kind}' cannot embed")
            ok = True
            return np.asarray(out, dtype=np.float32)
        finally:
            self._audit(t, app, tier, f"embed x{len(texts)}", None, None, None,
                        int((time.time() - start) * 1000), ok)

    def _st(self, model: str):
        if model not in self._st_models:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ProviderError("Install the local-embed extra: pip install 'phd-commons[local-embed]'") from e
            self._st_models[model] = SentenceTransformer(model)
        return self._st_models[model]

    # ---------- rerank (optional role)
    def rerank(self, query: str, passages: list[str], tier: str = "PUBLIC") -> list[float] | None:
        if "rerank" not in self.roles:
            return None
        t = self.resolve("rerank", tier)
        if t.provider.get("kind") != "sentence-transformers":
            return None
        key = "ce:" + t.model
        if key not in self._st_models:
            from sentence_transformers import CrossEncoder
            self._st_models[key] = CrossEncoder(t.model)
        return [float(s) for s in self._st_models[key].predict([(query, p) for p in passages])]

    # ---------- health
    def ping(self, role: str) -> tuple[bool, str]:
        try:
            if role == "embed":
                v = self.embed(["ping"], app="doctor/ping")
                return True, f"{v.shape[1]} dims"
            if role == "rerank":
                return True, "configured"
            out = self.chat(role, [{"role": "user", "content": "Reply with the single word: ready"}],
                            app="doctor/ping", max_tokens=64)
            if not out.strip():
                return False, ("empty reply: a reasoning model may be using its whole budget to think; "
                               "set thinking: off on this provider")
            return True, out[:40]
        except Exception as e:  # noqa: BLE001
            return False, str(e)[:160]
