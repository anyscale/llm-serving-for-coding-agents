# Cost estimate — self-hosting vs paying per token

A simple, reproducible **estimate** (±2×, not exact accounting) of what the Part 3 service costs per
developer per month, compared with sending the same agent traffic to a commercial LLM API at
per-token rates. All prices are rounded list prices (July 2026).

**TL;DR:** the same usage costs **≈ $100/dev-month** at typical frontier API token rates vs
**≈ $30/dev-month** self-hosted on an always-on RTX PRO 6000 (`g7e.4xlarge`, ≈ $2,900/mo,
~100 developers/GPU). The API wins below ≈ 25–30 developers because the GPU floor dominates;
above that, self-hosting wins — subject to the model-quality caveat below.

## Self-hosted side — three numbers

```
$/dev-month  =  monthly GPU cost  ÷  developers supported per GPU
             =  (GPU $/hr × 730)  ÷  (concurrent sessions per GPU ÷ duty cycle)
```

| # | Input | Value | Source |
|---|---|---|---|
| 1 | GPU price (`g7e.4xlarge` on-demand) | ≈ $4/hr → **≈ $2,900/mo** always-on | AWS list price |
| 2 | Concurrent Claude Code sessions per GPU | **≈ 24** | measured: 48 replayed sessions on 2 replicas at TTFT mean 7.8 s / p95 14 s ([`BENCHMARKS.md`](BENCHMARKS.md) §6, round-robin row) |
| 3 | Duty cycle — fraction of the workday one developer's session has a request in flight | **≈ 25%** planning number (10–40% range) | session-trace timestamps: ~35–40% in flight during active bursts; a full workday averages lower |

Agent traffic is bursty — the model streams for 10–30 s, then the developer reads and edits for
minutes — so one GPU serves far more developers than its 24 concurrent slots:

| Duty cycle | Devs per GPU | ≈ $/dev-month |
|---|---|---|
| 100% (everyone streaming nonstop — worst case) | 24 | $120 |
| 50% | 48 | $60 |
| **25% (planning number)** | **~100** | **$30** |
| 10% (typical mixed workday) | ~240 | $12 |

## API side — the same traffic, priced per token

Coding agents are billed by tokens, so the fair comparison is the API bill for the **same usage
profile** the GPU serves. From the measured workload (Claude Code session replays,
[`BENCHMARKS.md`](BENCHMARKS.md)): each agent turn re-sends the whole conversation — roughly 70K
input tokens, of which all but a few thousand are repeated context that APIs bill at cached rates —
and produces a short output.

Per turn, at typical frontier-model rates (≈ $3/MTok input, ≈ $15/MTok output, cached input ≈ 0.1×;
similar across providers):

| Component | Tokens/turn | Rate | ≈ $/turn |
|---|---|---|---|
| Context re-read (cached input) | ~66K | $0.30/MTok | $0.020 |
| New input | ~4K | $3/MTok | $0.012 |
| Output | ~150 | $15/MTok | $0.002 |
| **Total** | ~70K | | **≈ $0.034** |

A moderately active agent developer runs ≈ 50 turns per active hour (that pace is what produces the
measured 35–40% in-flight burst duty at ~23 s per turn) for ~2–4 hours a day:

```
~50 turns/hr × 2–4 hr/day × 21 days ≈ 2,000–4,000 turns/month
× $0.034/turn ≈ $70–140/dev-month   →  planning number ≈ $100
```

That is ~150–300 MTok of (mostly cached) context re-reads per developer per month — which is why
the comparison must be token-based with caching modeled, not raw list $/MTok.

## Comparison by team size

Self-hosted at the 25% planning number (~100 devs/GPU, GPUs added as `ceil(devs / 100)`), API at
the ≈ $100/dev-month planning number:

| Team size | GPUs | Self-hosted ≈ $/dev-mo | API ≈ $/dev-mo | Cheaper option |
|---|---|---|---|---|
| 10 | 1 | $290 | $100 | API |
| 25 | 1 | $115 | $100 | ≈ tie |
| 50 | 1 | $60 | $100 | self-hosted |
| 100 | 1 | $30 | $100 | self-hosted |
| 250 | 3 | $35 | $100 | self-hosted |

**Rule of thumb: one always-on GPU ≈ $2,900/mo ≈ the API bill of ~30 moderately active agent
developers.**

*(For reference, subscription seats cap the API bill at flat rates — Cursor Pro/Pro+/Ultra
$20/$60/$200, Claude Pro/Max $20/$100/$200 per dev-month. A ~$100 seat lands almost exactly on the
API planning number, so the break-even barely moves if seats are on the table.)*

## Caveats

- **Quality gap:** a 27B model vs a frontier model — cheaper per token isn't automatically cheaper
  per task if it takes more iterations to finish the same work.
- The API math assumes prompt caching applies to essentially all repeated context. Without caching
  the per-turn cost is ~6× higher; with a provider that discounts cache reads less than 10×, scale
  the cached-input row accordingly.
- These are rounded list prices and usage estimates; treat every number as ±2×.
- The service autoscales 1→4 (see [`service_optimized.yaml`](service_optimized.yaml)), so
  nights/weekends cost less than the always-on figure used here; spot pricing lowers it further.
  We quote always-on on-demand as the conservative case. Note `g7e` capacity can be flaky —
  spot-first with cross-zone scaling is the workaround.
- To tighten the numbers for your org, capture one real workday of agent traffic and count turns,
  tokens per turn, and `Σ(request wall time) / session wall time` — no GPU needed.

## Pricing sources

[AWS G7e announcement](https://aws.amazon.com/blogs/aws/announcing-amazon-ec2-g7e-instances-accelerated-by-nvidia-rtx-pro-6000-blackwell-server-edition-gpus/) ·
[g7e.4xlarge pricing](https://www.devzero.io/instances/aws/g7e.4xlarge) ·
[Claude API pricing](https://claude.com/pricing) ·
[OpenAI API pricing](https://openai.com/api/pricing/) ·
[Cursor pricing](https://cursor.com/pricing)

← Back: [Part 3 README](README.md) · Benchmarks: [`BENCHMARKS.md`](BENCHMARKS.md) · Overview: [top-level README](../README.md)
