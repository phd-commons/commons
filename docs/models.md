# Bring your own LLM

Commons never names a model in its code. It resolves models by role, and you decide which provider and model
serves each role in `commons.yaml`.

## Roles

| Role | Job | What matters |
|---|---|---|
| `author` | Answers questions, drafts reports | The strongest model you can run |
| `worker` | Extracts claims, screens the daily feed, links evidence | Speed and reliable JSON; runs thousands of times |
| `verifier` | Judges whether a quote supports a claim | A **different model family** from the author |
| `embed` | Turns text into vectors for search | One model for the life of the index |
| `rerank` (optional) | Re-orders retrieved passages | Small cross-encoder |

## Providers

```yaml
providers:
  ollama:
    kind: openai                       # any OpenAI-compatible server
    base_url: http://127.0.0.1:11434/v1
    locality: local
  uni:
    kind: openai
    base_url: https://ai.example.edu/v1
    api_key_env: UNI_AI_KEY            # read from the environment, never stored in the file
    locality: institutional
    restricted_approval: "HREC 2026/123 permits processing of de-identified transcripts on this service"
  claude:
    kind: anthropic
    api_key_env: ANTHROPIC_API_KEY
    locality: cloud
  st:
    kind: sentence-transformers        # in-process local embeddings and reranking
    locality: local

roles:
  author:   {provider: claude, model: "<a current Claude model id>", family: claude,
             local_fallback: {provider: ollama, model: "qwen3:8b"}}
  worker:   {provider: ollama, model: "qwen3:8b", family: qwen}
  verifier: {provider: ollama, model: "gemma3:12b", family: gemma}
  embed:    {provider: ollama, model: bge-m3}

cloud:
  public: true      # cloud providers may see published material
  private: false    # but not your drafts and notes
```

Kinds:

- `openai`: chat at `/chat/completions`, embeddings at `/embeddings`. Ollama, LM Studio, llama.cpp server, vLLM,
  `mlx_lm.server`, many university gateways and most hosted APIs offer this. Optional `headers`, `extra_body` and
  `json_mode: true` (sends `response_format`) for servers that support them.
  Set `thinking: off` on a provider serving a reasoning model (Qwen3 and similar) so that bulk jobs answer directly
  instead of spending their budget thinking; Commons sends the standard switches (`/no_think` and
  `chat_template_kwargs`), and retries once with more room if a reply still comes back empty. The Ollama and MLX
  presets set it already.
- `anthropic`: Anthropic's Messages API.
- `sentence-transformers`: local embeddings and reranking inside the Commons process (`pip install "phd-commons[local-embed]"`).
- `fake`: the deterministic demo stand-in. It is not a model.

## Locality, and what each provider may see

| | PUBLIC | PRIVATE | RESTRICTED |
|---|---|---|---|
| `local` | yes | yes | yes |
| `institutional` | yes | yes | only with `restricted_approval` |
| `cloud` | if `cloud.public` | if `cloud.private` | never |

Your propositions are your own drafts, so prompts that include them (claim extraction, linking, the daily screen)
run at the PRIVATE tier, set by `thesis_tier` in `commons.yaml`. Under the `hosted` and `anthropic` presets those
prompts therefore go to the local fallback, not the hosted model. Questions you type into Ask are treated as
PUBLIC; do not paste confidential material into a question if your author model is a cloud model.

A provider marked `local` that is not on your machine or a private network (an `anthropic` provider, or an
`openai` provider with a public address) is treated as cloud whatever its label says, and `commons doctor` shows
it in red.

`local_fallback` on a role lets material the main provider may not see go to a local model instead. `commons
doctor` flags a provider marked `local` whose address is not on your machine or private network.

Embeddings are the exception: an index must use one embedding model throughout, so `embed` cannot have a fallback.
If you will hold RESTRICTED material, make the embedder local from the start. Changing it later means
`commons rebuild`.

## Sizing

Budget about 80 per cent of the memory your models can use: VRAM on a PC with a GPU, unified memory on Apple
Silicon (macOS lets the GPU use roughly two thirds to three quarters of it by default). CPU-only machines work,
slowly. The model names below were current when this was written; newer releases in the same size class are
usually better.

| Budget | Runtime | author | worker | verifier |
|---|---|---|---|---|
| 250 GB and up | MLX | 235B-class mixture of experts, 4 to 6-bit | 30B-class MoE | gpt-oss-120b |
| 90 to 250 GB | MLX or Ollama | 80B to 120B-class MoE | 30B-class MoE | a different family, similar size |
| 24 to 90 GB | Ollama or LM Studio | 30B-class MoE, 4-bit | 8B-class | a different family, about 12B |
| 10 to 24 GB | Ollama | 8B to 14B-class | 4B to 8B-class | a different family, 4B to 12B |
| under 10 GB | Ollama | a hosted model for PUBLIC with a small local fallback, or a 4B-class local model | 4B-class | a different family, 4B-class |

For embeddings, `bge-m3` (1024 dimensions, long inputs, multilingual) is a sound default and runs anywhere.

## Model origin

Many of the strongest open-weight models come from a handful of labs in a few countries. If the origin of a model
matters to your project or your institution, record it (`family` and a comment in `commons.yaml`), keep a second
configuration with models of other origins, and say which you used in your methodology chapter.

## Speed on Apple Silicon

Generating text on a large mixture-of-experts model is fast; processing a long prompt is the slow part. Commons
keeps answer contexts to about 10,000 tokens after reranking (`retrieval.context_tokens`). Bulk work (claim
extraction, the daily screen) runs on the `worker` role and overnight.
