# Cost estimate — self-hosting vs coding-assistant seats

A simple, reproducible **estimate** (±2×, not exact accounting) of what the Part 3 service costs per
developer per month, compared with buying Claude Code or Cursor seats. All prices are rounded list
prices (July 2026).

**TL;DR:** one always-on RTX PRO 6000 (`g7e.4xlarge`, ≈ $2,900/mo) serves roughly 100 developers
with realistic agent usage → **≈ $30/dev-month**. Seats win below ≈ 25–30 developers; above that,
self-hosting costs less than any commercial seat — subject to the model-quality caveat below.

## The model — three numbers

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

## Comparison by team size

At the 25% planning number (~100 devs/GPU), GPUs added as `ceil(devs / 100)`:

| Team size | GPUs | Self-hosted ≈ $/dev-mo | Claude Max 5x seat | Cheaper option |
|---|---|---|---|---|
| 10 | 1 | $290 | $100 | seats |
| 25 | 1 | $115 | $100 | ≈ tie |
| 50 | 1 | $60 | $100 | self-hosted |
| 100 | 1 | $30 | $100 | self-hosted |
| 250 | 3 | $35 | $100 | self-hosted |

**Rule of thumb: one always-on GPU ≈ $2,900/mo ≈ 29 Claude Max-5x seats.**

Seat prices for reference:

| Seat | $/dev-month |
|---|---|
| Cursor Pro / Pro+ / Ultra | $20 / $60 / $200 |
| Cursor Teams | $40–120 |
| Claude Pro / Max 5x / Max 20x | $20 / $100 / $200 |
| Claude Team Premium (with Claude Code) | $100–125 |

## Caveats

- **Quality gap:** a 27B model vs a frontier model — cheaper per token isn't automatically cheaper
  per task if it takes more iterations to finish the same work.
- These are rounded list prices and a duty-cycle estimate; treat every number as ±2×.
- The service autoscales 1→4 (see [`service_optimized.yaml`](service_optimized.yaml)), so
  nights/weekends cost less than the always-on figure used here; spot pricing lowers it further.
  We quote always-on on-demand as the conservative case. Note `g7e` capacity can be flaky —
  spot-first with cross-zone scaling is the workaround.
- To tighten the duty-cycle number for your org, capture one real workday of agent traffic and
  compute `Σ(request wall time) / session wall time` — no GPU needed.

## Pricing sources

[AWS G7e announcement](https://aws.amazon.com/blogs/aws/announcing-amazon-ec2-g7e-instances-accelerated-by-nvidia-rtx-pro-6000-blackwell-server-edition-gpus/) ·
[g7e.4xlarge pricing](https://www.devzero.io/instances/aws/g7e.4xlarge) ·
[Cursor pricing](https://cursor.com/pricing) ([plan breakdown](https://dev.to/rahulxsingh/cursor-pricing-in-2026-hobby-pro-pro-ultra-teams-and-enterprise-plans-explained-4b89)) ·
[Claude pricing](https://claude.com/pricing) ([Claude Code plan guide](https://www.ssdnodes.com/blog/claude-code-pricing-in-2026-every-plan-explained-pro-max-api-teams/), [Max plan details](https://support.claude.com/en/articles/11049741-what-is-the-max-plan))

← Back: [Part 3 README](README.md) · Benchmarks: [`BENCHMARKS.md`](BENCHMARKS.md) · Overview: [top-level README](../README.md)
