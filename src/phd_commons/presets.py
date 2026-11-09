"""Provider presets for `commons init --preset`. Model names are starting points; edit commons.yaml freely.

Pick by hardware (see docs/models.md):
  demo         no models at all; the deterministic fake provider, to try the workflow
  ollama       any OS, 16 GB RAM or more; Ollama serving local models
  lmstudio     any OS; LM Studio's local server
  mlx          Apple Silicon with 64 GB or more; mlx_lm.server processes
  hosted       an OpenAI-compatible hosted API for PUBLIC material, Ollama locally for everything else
  anthropic    Claude for PUBLIC material, Ollama locally for everything else
"""

OLLAMA = {"kind": "openai", "base_url": "http://127.0.0.1:11434/v1", "locality": "local"}

PRESETS: dict[str, dict] = {
    "demo": {
        "providers": {"fake": {"kind": "fake", "locality": "local"}},
        "roles": {r: {"provider": "fake", "model": f"fake-{r}"} for r in ("author", "worker", "verifier", "embed")},
    },
    "ollama": {
        "providers": {"ollama": OLLAMA},
        "roles": {
            "author": {"provider": "ollama", "model": "qwen3:30b", "family": "qwen"},
            "worker": {"provider": "ollama", "model": "qwen3:8b", "family": "qwen"},
            "verifier": {"provider": "ollama", "model": "gemma3:12b", "family": "gemma"},
            "embed": {"provider": "ollama", "model": "bge-m3"},
        },
    },
    "lmstudio": {
        "providers": {"lmstudio": {"kind": "openai", "base_url": "http://127.0.0.1:1234/v1", "locality": "local"}},
        "roles": {
            "author": {"provider": "lmstudio", "model": "SET-ME: the model id LM Studio shows", "family": ""},
            "worker": {"provider": "lmstudio", "model": "SET-ME", "family": ""},
            "verifier": {"provider": "lmstudio", "model": "SET-ME: a different model family", "family": ""},
            "embed": {"provider": "lmstudio", "model": "SET-ME: an embedding model, e.g. bge-m3"},
        },
    },
    "mlx": {
        "providers": {
            "mlx_author": {"kind": "openai", "base_url": "http://127.0.0.1:8811/v1", "locality": "local"},
            "mlx_worker": {"kind": "openai", "base_url": "http://127.0.0.1:8812/v1", "locality": "local"},
            "mlx_verifier": {"kind": "openai", "base_url": "http://127.0.0.1:8813/v1", "locality": "local"},
            "st": {"kind": "sentence-transformers", "locality": "local"},
        },
        "roles": {
            "author": {"provider": "mlx_author", "model": "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit", "family": "qwen"},
            "worker": {"provider": "mlx_worker", "model": "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit", "family": "qwen"},
            "verifier": {"provider": "mlx_verifier", "model": "mlx-community/gpt-oss-20b-MXFP4-Q8", "family": "gpt-oss"},
            "embed": {"provider": "st", "model": "BAAI/bge-m3"},
            "rerank": {"provider": "st", "model": "BAAI/bge-reranker-v2-m3"},
        },
    },
    "hosted": {
        "providers": {
            "hosted": {"kind": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY",
                       "locality": "cloud"},
            "ollama": OLLAMA,
        },
        "cloud": {"public": True, "private": False},
        "roles": {
            "author": {"provider": "hosted", "model": "SET-ME", "family": "",
                       "local_fallback": {"provider": "ollama", "model": "qwen3:8b"}},
            "worker": {"provider": "hosted", "model": "SET-ME", "family": "",
                       "local_fallback": {"provider": "ollama", "model": "qwen3:8b"}},
            "verifier": {"provider": "ollama", "model": "gemma3:12b", "family": "gemma"},
            "embed": {"provider": "ollama", "model": "bge-m3"},
        },
    },
    "anthropic": {
        "providers": {
            "anthropic": {"kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "locality": "cloud"},
            "ollama": OLLAMA,
        },
        "cloud": {"public": True, "private": False},
        "roles": {
            "author": {"provider": "anthropic", "model": "SET-ME: a current Claude model id", "family": "claude",
                       "local_fallback": {"provider": "ollama", "model": "qwen3:8b"}},
            "worker": {"provider": "ollama", "model": "qwen3:8b", "family": "qwen"},
            "verifier": {"provider": "ollama", "model": "gemma3:12b", "family": "gemma"},
            "embed": {"provider": "ollama", "model": "bge-m3"},
        },
    },
}
