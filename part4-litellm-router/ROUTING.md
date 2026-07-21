# How the smart router decides

The gateway exposes three model names you can pick with `/model`:

| Model name | Backend |
|---|---|
| `anyscale-qwen3.6-27b` | your Anyscale LLM service (always) |
| `claude-opus-4-8` | Anthropic Claude Opus (always; your Claude subscription) |
| `smart-router` | **decides automatically** per request (this doc) |

Only `smart-router` makes a decision. The other two are hard-wired.

## Decision flow (per request)

![LiteLLM router gateway: request path (left) and smart-router decision flow (right)](./architecture_diagram.drawio.png)

The right panel is the per-request decision this doc explains: **1.** keyword
overrides in the prompt force a tier, otherwise **2.** 2+ reasoning markers force
REASONING, otherwise **3.** a complexity score (0–1) picks the tier; the tier →
model map sends SIMPLE/MEDIUM/COMPLEX to `anyscale-qwen3.6-27b` and REASONING to
`claude-opus-4-8`, and any error/timeout retries once then falls back to
`claude-opus-4-8` (`router_settings.fallbacks`). The editable source is
[`architecture_diagram.drawio`](./architecture_diagram.drawio).

Steps 1–3 are **local, rule-based, <1 ms, zero API calls** — nothing is sent to
an LLM to make the routing decision.

## 1. Keyword overrides (`keyword_tier_rules`) — how users steer it

Checked first. If any keyword appears in the latest user message, that rule's
tier is forced (skipping scoring). Current rules (`gateway/config.yaml`):

| Say this in your prompt | Forced tier | → model |
|---|---|---|
| `use opus`, `opus 4.8`, `opus4.8`, `use claude`, `use reasoning`, or invoking the **`/fix`** skill | REASONING | `claude-opus-4-8` |
| `use qwen`, `use local`, `use the local model`, `use anyscale`, `use anyscale llm`, `use oss`, `use the oss model`, `use open model`, `open source model`, `oss model`, `open model`, or invoking the **`/ask`** skill | SIMPLE | `anyscale-qwen3.6-27b` |

- **Most-severe wins:** if a message hits both a SIMPLE and a REASONING keyword,
  REASONING wins (order-independent).
- **Matching:** multi-word phrases match as substrings; single words match on
  word boundaries (so `opus` wouldn't match `corpus`). Case-insensitive.
- **Slash keywords need exact spellings:** a bare `/fix` keyword would never
  match — space-less keywords get word-boundary regex, and `\b` fails between a
  space (or start of message) and `/`. The config therefore uses `"/fix "`
  (trailing space → substring match) to catch `/fix ...` typed in a prompt, and
  `"command-name>/fix"` to catch the `<command-name>/fix</command-name>` block
  Claude Code sends when the skill is invoked (same pair for `/ask`). Edge
  case: typing `/fix` as the entire message, where no skill expansion happens,
  matches neither spelling and falls through to scoring.

## 2. Reasoning override

If the **user** message contains **2+ reasoning markers** (`step by step`,
`think through`, `analyze`, …), it's forced to REASONING regardless of score.
Markers in the *system* prompt are ignored (so a "think step by step" system
prompt doesn't send everything to Opus).

## 3. Complexity score (when no override fires)

The last user message is scored across 7 weighted dimensions, summed to a
0–1 score, then bucketed into a tier:

| Dimension | Weight | Raises score when the prompt has… |
|---|---|---|
| `codePresence` | 0.30 | code words: `function`, `class`, `def`, `debug`, `refactor`, `api`, `docker`… |
| `reasoningMarkers` | 0.25 | `step by step`, `think through`, `analyze`… |
| `technicalTerms` | 0.25 | technical / domain vocabulary |
| `tokenCount` | 0.10 | long prompt (>400 tok ↑); short (<15 tok ↓) |
| `simpleIndicators` | 0.05 (neg) | `what is`, `define` (lowers score) |
| `multiStepPatterns` | 0.03 | `first… then`, numbered steps |
| `questionComplexity` | 0.02 | multiple `?` |

| Score | Tier | → model |
|---|---|---|
| < 0.15 | SIMPLE | `anyscale-qwen3.6-27b` |
| 0.15–0.35 | MEDIUM | `anyscale-qwen3.6-27b` |
| 0.35–0.60 | COMPLEX | `anyscale-qwen3.6-27b` |
| > 0.60 | REASONING | `claude-opus-4-8` |

So by default only genuinely hard prompts reach Claude; everything else stays
on your local model.

> **Note:** `REASONING` is just a **label for the top complexity bucket** — it
> does **not** mean "route to a reasoning model." Each tier (including
> `REASONING`) maps to whatever model you put in `tiers`. Here `REASONING` →
> `claude-opus-4-8`, but you could point it at any model. The four tier names
> (`SIMPLE`/`MEDIUM`/`COMPLEX`/`REASONING`) are fixed; the model each maps to,
> and the score boundaries, are yours to configure.

## Fallback (separate from routing)

Whatever model routing picks, if the request **errors / times out / rate-limits**,
`router_settings.fallbacks` retries once then sends it to `claude-opus-4-8`.
This is failure handling, **not** quality-based — a bad answer returned with
HTTP 200 does not trigger fallback.

## Caveats

- **No negation awareness.** "do not use opus" still matches `use opus` → routes
  to Opus. Pick trigger phrases users won't type in the negative.
- **Last user message only.** Per-turn — great for switching mid-conversation.
- **Claude paths need OAuth.** `claude-opus-4-8` (and REASONING-tier routing)
  work only from Claude Code, which forwards your Claude subscription token.

## Customizing the router

All in `gateway/config.yaml` under `complexity_router_config`:

| Want to… | Change |
|---|---|
| Add/booster keyword triggers | add entries to `keyword_tier_rules` |
| Send moderately-hard tasks to Opus too | map `COMPLEX: *fallback`, or lower the boundary via `tier_boundaries: {complex_reasoning: 0.45}` |
| Re-tune what counts as "complex" | `tier_boundaries`, `dimension_weights`, `code_keywords`, `reasoning_keywords` |
| Fuzzy/semantic keyword matching (paraphrases) | `semantic_keyword_matching: true` + `embedding_model:` + `match_threshold:` (needs an embedding endpoint; reintroduces the negation issue) |
| Swap the backend model entirely | see the "TO SWAP THE BACKEND MODEL" header in `gateway/config.yaml` — change the `&primary` anchor + the 3 `LOCAL_LLM_*` env vars |

After editing `gateway/config.yaml`, redeploy:
`anyscale service deploy -f service.yaml` (from the `gateway/` directory).
