# Cost estimate: self-hosting vs paying per token

This page answers one question:

> If a team uses the Part 3 coding-agent service, is it cheaper to run the model ourselves or send
> the same traffic to a commercial LLM API?

This is a planning estimate, not exact accounting. Treat every number as ±2×. Prices are rounded
list prices from July 2026.

## Short Answer

Commercial pricing comes in two scenarios, and the comparison should be made against both:

1. **Scenario 1 — Subscription seats, ≈ $200/dev-month.** A Claude Max 20x or Cursor Ultra seat
   caps an individual heavy user at about $200/month, with usage limits attached.
2. **Scenario 2 — Token-metered billing, ≈ $800/dev-month.** When usage bills per token
   (API keys, or enterprise tiers past the seat cliff), real coding-agent bills land near
   $800/dev-month for active engineers — Pylon measured ≈ $780.

The same traffic on a self-hosted RTX PRO 6000 GPU:

| Mode | GPU cost | Cost per developer | Break-even vs $200 seat | Break-even vs $800 tokens |
|---|---:|---:|---:|---:|
| Always-on, on-demand | ≈ $2,900/mo | **≈ $30/mo** | ~15 developers | ~4 developers |
| Always-on, spot | ≈ $1,700/mo | **≈ $17/mo** | ~9 developers | ~2 developers |
| Work-hours, on-demand | ≈ $840/mo | **≈ $8/mo** | ~4 developers | ~1 developer |
| Work-hours, spot | ≈ $480/mo | **≈ $5/mo** | ~3 developers | **even 1 developer** |

Read it this way: against the *friendliest* commercial case — the $200 capped seat — self-hosting
wins above roughly 3–15 developers depending on mode. Against token-metered billing, the case is
much stronger: one GPU costs less than four token-metered developers even always-on, and in
work-hours + spot mode the GPU is cheaper than a *single* heavy developer's token bill.

The biggest caveat is model quality: a cheaper 27B model only saves money if it completes the same
work with an acceptable number of extra turns.

## What This Estimate Assumes

The self-hosted side uses the optimized Part 3 service on one `g7e.4xlarge` instance with an RTX PRO
6000 GPU. The API side prices the same coding-agent traffic at typical frontier-model token rates.

| Input | Planning value | Why it matters |
|---|---:|---|
| GPU price, on-demand | ≈ $4.00/hr | About $2,900/month if always on |
| GPU price, spot | ≈ $2.27/hr | About 43% cheaper than on-demand |
| Active sessions per GPU | ≈ 24 | Measured from 48 replayed Claude Code sessions on 2 replicas |
| Developer duty cycle | ≈ 25% | Agent traffic is bursty: stream, read, edit, repeat |
| Input tokens per turn | ≈ 70K | Measured: each turn re-sends the whole session history |
| — repeated context in that | ≈ 66K | System prompt + tool schemas (~57K) + prior turns; cached |
| — new tokens per turn | ≈ 4K | The latest user message / tool result increment |
| Output tokens per turn | ≈ 150 | Measured range 60-209; agent turns are short answers or tool calls |
| API cost per turn | ≈ $0.05 | Blends warm cached turns and cold cache rewrites |
| Turns per developer | ≈ 2,000-4,000/month | About 2-4 active agent hours/day, 21 workdays/month |

The most important assumption is duty cycle. A developer does not stream tokens continuously all
day. They send a request, wait 10-30 seconds, then spend minutes reading, editing, testing, or
thinking. That burstiness lets one GPU serve far more developers than its raw concurrent-session
count.

### Where the Token Numbers Come From

The token lengths are measured, not guessed, from real Claude Code sessions captured through a
local API proxy and replayed against the service:

- **Server side:** replaying the sessions through vLLM measured a median prompt of ≈ 69.7K tokens
  and a max of ≈ 81K ([`BENCHMARKS.md`](BENCHMARKS.md)). A Claude Code request is dominated by a
  byte-identical ~57K-token prefix (system prompt + ~147 tool schemas), with conversation history
  on top.
- **Client side:** the captured API responses include per-turn `usage` accounting, and it shows the
  same shape. A session's *first* turn cache-writes the full context (30K-105K tokens across the
  captured sessions, depending on how much history had accumulated). Every *later* turn cache-reads
  that context back and writes only a ~2.5K-token increment, with single-digit uncached input
  tokens and 43-188 output tokens.
- **Per session:** context length grows toward the 70-80K range once the tool schemas and a few
  turns of history render, which is why ≈ 70K input / ≈ 150 output per turn is the planning
  average. Early turns in a fresh session are cheaper (~30K); long sessions approach the 81K max
  we measured.

## Self-Hosted Cost

The self-hosted formula is:

```text
$/dev-month = monthly GPU cost / developers supported per GPU

developers supported per GPU = concurrent active sessions / duty cycle
```

With 24 active sessions per GPU:

| Duty cycle | What it means | Developers per GPU | Always-on cost/dev |
|---|---|---:|---:|
| 100% | Everyone streams nonstop | 24 | $120/mo |
| 50% | Very heavy usage | 48 | $60/mo |
| 25% | Planning number | ~100 | $30/mo |
| 10% | Light or mixed workday | ~240 | $12/mo |

So the default planning number is:

```text
$2,900/month per always-on GPU / ~100 developers = ~$30/dev-month
```

## Work-Hours Scale-to-Zero

If developers mostly use the service during the workday, the GPU does not need to run overnight or
on weekends. The scale-to-zero setup uses:

- [`scale-to-zero/service_scale_to_zero.yaml`](scale-to-zero/service_scale_to_zero.yaml), with
  `MIN_REPLICAS=0` and `min_nodes: 0`.
- [`scale-to-zero/warmup.sh`](scale-to-zero/warmup.sh), scheduled around 7 am on weekdays.
- [`scale-to-zero/warmup_schedule.yaml`](scale-to-zero/warmup_schedule.yaml), applied with
  `anyscale schedule apply`, or any external cron runner.

The planning math:

```text
10 hours/day * 21 weekdays = ~210 GPU-hours/month
~210 GPU-hours * $4/hr = ~$840/month
~$840/month / ~100 developers = ~$8/dev-month
```

That is the target cost, but scale-to-zero has operational trade-offs:

- **Cold starts:** measured on 2026-07-06 at ≈ 100 seconds when the node is still up, and ≈ 6
  minutes when a new node must be provisioned.
- **Retry behavior:** the first waking request can hang without a useful response, so `warmup.sh`
  retries instead of sending one ping.
- **Off-hours usage:** late-night and weekend users either wait through the cold start or fall back
  to a commercial API.
- **Billing reality:** actual cost depends on real traffic and the scale-down delay, not just the
  10-hour planning assumption.

> **Validation status (2026-07-06):** replica scale-to-zero is confirmed working, but in our live
> test the **GPU node itself never terminated**. The app's CPU router deployment can land on the
> only worker type, which is the GPU node, and keep it alive. Until the router runs on the head node
> or a small CPU worker pool, treat work-hours cost as the target, not a guarantee. After enabling
> this mode, check the cluster nodes page and confirm the `g7e` instance terminates after about 35
> idle minutes.

## Spot Instances

Spot cuts GPU cost from about **$4.00/hr** to **$2.27/hr** in `us-west-2`, or about 43% cheaper.
The Part 3 config uses spot with on-demand fallback via `market_type: PREFER_SPOT`; cross-zone
scaling improves availability.

The trade-off is interruption. Spot instances can be preempted with a 2-minute warning. The service
then restarts the replica on a fresh node. With the Part 3 fast-start work, recovery is on the order
of the measured ~3-minute cold start. Because `PREFER_SPOT` falls back to on-demand when spot
capacity is tight, the main cost is latency, not full unavailability.

## API Cost

The API comparison prices the same coding-agent traffic by token. In the measured workload
([`BENCHMARKS.md`](BENCHMARKS.md)), each agent turn re-sends the whole conversation:

- About **70K input tokens** per turn.
- Most of those tokens are repeated context.
- Output is short, about **150 tokens** per turn.

Prompt caching helps, but it does not make repeated context free. At typical frontier-model rates:

- Base input: ≈ $3/MTok.
- Output: ≈ $15/MTok.
- Cache reads: 0.1× base input, or ≈ $0.30/MTok.
- Cache writes: 1.25× base input, or ≈ $3.75/MTok.
- Cache expiry: about 5 idle minutes.

That creates two turn types.

**Warm turn:** the previous turn was less than 5 minutes ago, so most context is a cache hit.

| Component | Tokens/turn | Rate | Cost/turn |
|---|---:|---:|---:|
| Context re-read | ~66K | $0.30/MTok | $0.020 |
| New input cache write | ~4K | $3.75/MTok | $0.015 |
| Output | ~150 | $15/MTok | $0.002 |
| **Warm total** | ~70K | | **≈ $0.04** |

**Cold turn:** the first turn of a session, or any turn after a pause longer than ~5 minutes, writes
the full ~70K-token context back into the cache:

```text
~70K tokens * $3.75/MTok = ~$0.26
```

That is about 7× more expensive than a warm turn. With roughly 1 cold turn per 10-20 turns, the
blended estimate is **≈ $0.05/turn**.

Monthly API cost for a moderately active developer:

```text
~50 turns/hour * 2-4 active hours/day * 21 days = ~2,000-4,000 turns/month
~2,000-4,000 turns * $0.05/turn = ~$100-200/dev-month
planning number = ~$150/dev-month
```

That is roughly 150-300 MTok of context reads and writes per developer per month. Opus-class rates
($5/$25) raise the API column by about 1.7×. Top-tier rates ($10/$50) raise it by about 3.3×.

This bottom-up ~$150 is the *moderate-usage floor* of Scenario 2. It sits just under the $200
subscription cap — which is why the seats are priced where they are — and measured heavy usage
(higher turn volume, pricier models, parallel agents) lands near the ~$800 Scenario 2 planning
number.

Self-hosting avoids this cache-expiry cost structure: vLLM prefix-cache hits and writes are not
billed per token, and KV blocks are evicted under memory pressure rather than after a 5-minute idle
timer.

## Team-Size Comparison

This table uses the 25% duty-cycle planning number: about 100 developers per GPU, with GPUs added as
`ceil(developers / 100)`. The two commercial columns are the flat scenario prices. Self-hosted rows
are on-demand; multiply by about 0.57 for spot.

| Team size | GPUs | Always-on self-hosted | Work-hours self-hosted | Scenario 1: $200 seat | Scenario 2: $800 tokens |
|---|---:|---:|---:|---:|---:|
| 10 | 1 | $290/dev-mo | $84/dev-mo | $200/dev-mo | $800/dev-mo |
| 25 | 1 | $115/dev-mo | $34/dev-mo | $200/dev-mo | $800/dev-mo |
| 50 | 1 | $60/dev-mo | $17/dev-mo | $200/dev-mo | $800/dev-mo |
| 100 | 1 | $30/dev-mo | $8/dev-mo | $200/dev-mo | $800/dev-mo |
| 250 | 3 | $35/dev-mo | $10/dev-mo | $200/dev-mo | $800/dev-mo |

The monthly totals make the incentive concrete. At 100 developers:

- Scenario 1 (subscriptions): 100 × $200 = **$20K/month**.
- Scenario 2 (token-metered): 100 × $800 = **$80K/month**.
- Self-hosted: **$2.9K/month** always-on, **$840/month** work-hours — roughly **7-95× cheaper**.

Rules of thumb:

- One always-on GPU costs about **$2,900/month** — roughly **15** subscription seats, or the token
  bill of just **~4** heavy developers.
- Work-hours mode costs about **$840/month** — about **4** seats, or ~1 token-metered developer.
- Spot lowers the self-hosted side by about **43%**.

## Scenario 1: Subscription Seats (≈ $200/dev-month)

Subscription seats can cap individual spend at flat monthly rates:

- Cursor Pro/Pro+/Ultra: $20/$60/$200 per developer per month.
- Claude Pro/Max: $20/$100/$200 per developer per month.

The $200 tiers (Max 20x, Cursor Ultra) are the realistic planning number for engineers who use
coding agents seriously — the cheaper tiers rate-limit heavy agent use. Those tiers sit just above
the ~$150 token-metered estimate for a moderate user, so for individuals the seat is competitive.

Two limits make this the *best case* for the commercial side, not the default:

- **Usage caps.** Seats include limited usage; sustained heavy use hits the plan limits.
- **The enterprise cliff.** After 150 seats, Anthropic's Enterprise tier stops acting like a flat
  cap and moves usage much closer to standard token-metered billing — which turns Scenario 1 into
  Scenario 2 overnight, the jump Pylon reported.

## Scenario 2: Token-Metered Billing (≈ $800/dev-month)

Pylon, a ~150-engineer startup, [reported](https://x.com/marty_kausas/status/2064739372625232068)
a $400K/year Anthropic bill on seats, or about **$220/dev-month**, that was about to jump to
$1.4M/year, or about **$780/dev-month**. Marty Kausas also reported burning thousands of dollars in
a few days himself, with top support reps around **$800/month** each. The jump happened because
crossing 150 seats moved them to an Enterprise tier where usage is billed much closer to standard
API/token-metered rates.

For heavy users, model both sides consistently:

- API cost can rise from the moderate **~$150/dev-month** estimate to **~$800/dev-month**.
- Self-hosted duty cycle also rises toward 100%, so one GPU supports closer to its raw **~24 active
  sessions**, not ~100 developers.
- Self-hosted cost rises to about **$120/dev-month** always-on, or about **$35/dev-month** in
  work-hours mode.

Even with that higher self-hosted cost, break-even falls to about **4 developers**, and self-hosting
can be roughly **6-20× cheaper** at scale. This is the scenario where self-hosting on Anyscale is
most compelling. The honest counterweight is that heavy users may rely more on frontier-model
quality, where the 27B model gap matters most.

## Caveats

- **Quality gap:** this compares a 27B self-hosted model with frontier APIs. Cheaper tokens are not
  cheaper work if the model needs many more attempts to finish the same task.
- **Cache assumptions:** the API estimate is sensitive to cold-turn frequency. Every pause longer
  than the ~5-minute cache TTL adds a ~$0.26 full-context cache rewrite.
- **Provider pricing:** different cache-read, cache-write, input, and output multipliers shift the
  API math proportionally.
- **Scale-to-zero validation:** [`service_optimized.yaml`](service_optimized.yaml) is the
  conservative always-on config. Work-hours numbers depend on the shipped
  [`scale-to-zero/`](scale-to-zero/) config, `warmup.sh`, and the GPU node actually terminating.
- **Spot availability:** spot prices float, and preemptions interrupt in-flight requests for a few
  minutes. `g7e` on-demand capacity can also be tight in a single AZ, so `PREFER_SPOT` plus
  cross-zone scaling has been the reliable combination in practice.
- **Org-specific usage:** to tighten the estimate, capture one real workday of agent traffic and
  count turns, tokens per turn, and `sum(request wall time) / session wall time`.

## Pricing Sources

[AWS G7e announcement](https://aws.amazon.com/blogs/aws/announcing-amazon-ec2-g7e-instances-accelerated-by-nvidia-rtx-pro-6000-blackwell-server-edition-gpus/) ·
[g7e.4xlarge pricing](https://www.devzero.io/instances/aws/g7e.4xlarge) ·
[Claude API pricing](https://claude.com/pricing) ·
[OpenAI API pricing](https://openai.com/api/pricing/) ·
[Cursor pricing](https://cursor.com/pricing) ·
[Pylon's seat-cliff post (X, 2026)](https://x.com/marty_kausas/status/2064739372625232068)

← Back: [Part 3 README](README.md) · Benchmarks: [`BENCHMARKS.md`](BENCHMARKS.md) · Overview: [top-level README](../README.md)
