# Cost estimate — self-hosting vs paying per token

A simple, reproducible **estimate** (±2×, not exact accounting) of what the Part 3 service costs per
developer per month, compared with sending the same agent traffic to a commercial LLM API at
per-token rates. All prices are rounded list prices (July 2026).

**TL;DR:** the same usage costs **≈ $150/dev-month** at typical frontier API token rates (with
prompt-cache reads, writes, and expiry modeled) vs **≈ $30/dev-month** self-hosted on an always-on
RTX PRO 6000 (`g7e.4xlarge`, ≈ $2,900/mo, ~100 developers/GPU) — or **≈ $8/dev-month** with
scale-to-zero outside work hours (GPU up ~10 h/day on weekdays, ≈ $840/mo). Spot instances
(≈ $2.3/hr, −43%) cut those to **≈ $17** and **≈ $5**. Always-on breaks even at ≈ 15–30
developers (spot ~11); work-hours mode at ≈ 5–10 (spot ~3) — subject to the model-quality caveat
below. Measured real-world heavy usage runs far higher — Pylon reported **≈ $780/dev-month** at
API rates — and at that intensity self-hosting breaks even at **~4 developers**.

## Self-hosted side — three numbers

```
$/dev-month  =  monthly GPU cost  ÷  developers supported per GPU
             =  (GPU $/hr × 730)  ÷  (concurrent sessions per GPU ÷ duty cycle)
```

| # | Input | Value | Source |
|---|---|---|---|
| 1 | GPU price (`g7e.4xlarge`, us-west-2) | **≈ $4/hr on-demand · ≈ $2.3/hr spot (−43%)** | AWS list/spot price |
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

### Cheaper still: scale to zero outside work hours

Developers only use the agent during the workday, so don't pay for the GPU overnight or on
weekends: deploy [`service_scale_to_zero.yaml`](service_scale_to_zero.yaml) (same deployment with
`MIN_REPLICAS=0` + `min_nodes: 0`) and schedule [`warmup.sh`](warmup.sh) at 7 am on weekdays —
either as an Anyscale scheduled job ([`warmup_schedule.yaml`](warmup_schedule.yaml), applied with
`anyscale schedule apply`) or from any box with cron — so the first developer of the day never
sees a cold start. Setup details in the [README](README.md#scale-to-zero-outside-work-hours).

```
10 h/day × 21 weekdays ≈ 210 GPU-hours/month × $4/hr ≈ $840/mo   (vs $2,900 always-on)
÷ ~100 devs/GPU  ≈  $8/dev-month
```

What scale-to-zero costs you in exchange:

- **Cold starts.** Scaling from zero waits for node provisioning plus startup. Measured
  (2026-07-06): **≈ 100 s** to wake when the node is still up (engine restart with the fast-start
  work), **≈ 6 min** end-to-end when a node must be provisioned. The waking request itself can
  hang without ever getting a response — clients must retry, which is why `warmup.sh` is a retry
  loop rather than a single ping.
- **Off-hours users** (late night, weekends) hit that cold start on their first request, or you
  keep a commercial API key as the off-hours fallback.
- 10 h/day is an assumption; actual billing follows real traffic plus the scale-down delay.

> **⚠ Validation status (2026-07-06):** replica scale-to-zero is confirmed working, but in our
> live test the **GPU node itself never terminated** — the app's CPU router deployment can land
> on the only worker type (the GPU node) and pin it, so billing continued as if always-on. Until
> the router is placed on the head node or a small CPU worker pool, treat the work-hours dollar
> figures as the *target*, not a given: after enabling this mode, verify on the cluster's nodes
> page that the `g7e` instance actually terminates after ~35 idle minutes.

### On-demand vs spot

Anyscale schedules workers on spot with on-demand fallback (`market_type: PREFER_SPOT` in the
compute config, ideally with cross-zone scaling for availability). At us-west-2 rates
($4.00 on-demand / $2.27 spot per hour), the four self-hosted modes at the ~100 devs/GPU planning
number:

| Mode | GPU $/hr | ≈ GPU $/mo | ≈ $/dev-mo | Break-even vs API ≈ $150 |
|---|---|---|---|---|
| Always-on, on-demand | $4.00 | $2,900 | $30 | ~20 devs |
| Always-on, spot | $2.27 | $1,700 | $17 | ~11 devs |
| Work-hours, on-demand | $4.00 | $840 | $8 | ~6 devs |
| **Work-hours, spot** | **$2.27** | **$480** | **$5** | **~3 devs** |

Spot's trade-off: instances can be preempted with a 2-minute warning, and the service then
restarts the replica on a fresh node — with the Part 3 fast-start work that recovery is on the
order of the measured ~3-minute cold start. `PREFER_SPOT` falls back to on-demand when spot
capacity is tight, so preemption costs you minutes of latency, not availability.

## API side — the same traffic, priced per token

Coding agents are billed by tokens, so the fair comparison is the API bill for the **same usage
profile** the GPU serves. From the measured workload (Claude Code session replays,
[`BENCHMARKS.md`](BENCHMARKS.md)): each agent turn re-sends the whole conversation — roughly 70K
input tokens, of which all but a few thousand are repeated context that APIs bill at cached rates —
and produces a short output.

Cache mechanics matter more than list $/MTok. At typical frontier-model rates (≈ $3/MTok base
input, ≈ $15/MTok output), cache **reads** are 0.1× base but cache **writes** are 1.25× base, and
the cache expires after ~5 idle minutes. So there are two kinds of turns:

**Warm turn** — the previous turn was < 5 min ago, so the whole history is a cache hit and only
the new tokens are written:

| Component | Tokens/turn | Rate | ≈ $/turn |
|---|---|---|---|
| Context re-read (cache hit, 0.1×) | ~66K | $0.30/MTok | $0.020 |
| New input (cache write, 1.25×) | ~4K | $3.75/MTok | $0.015 |
| Output | ~150 | $15/MTok | $0.002 |
| **Warm total** | ~70K | | **≈ $0.04** |

**Cold turn** — the first turn of a session, or any turn after a > 5-minute pause: the entire
~70K context is **re-written** to the cache at 1.25× → ~70K × $3.75/MTok ≈ **$0.26** — about 7×
a warm turn. Agent use is bursty, so pauses happen: with roughly 1 cold turn per 10–20 (session
starts, coffee breaks, meetings), the blended average is **≈ $0.05/turn**.

A moderately active agent developer runs ≈ 50 turns per active hour (that pace is what produces the
measured 35–40% in-flight burst duty at ~23 s per turn) for ~2–4 hours a day:

```
~50 turns/hr × 2–4 hr/day × 21 days ≈ 2,000–4,000 turns/month
× $0.05/turn ≈ $100–200/dev-month   →  planning number ≈ $150
```

That is ~150–300 MTok of context re-reads and re-writes per developer per month. Rates above are
Sonnet-class; an Opus-class model ($5/$25) scales the API column ≈ 1.7×, a top-tier model
($10/$50) ≈ 3.3×. The self-hosted side is immune to all of this: vLLM's prefix cache costs nothing
per hit or write, and KV blocks are evicted only under memory pressure, not on a 5-minute clock.

**Real-world anchor.** Pylon, a ~150-engineer startup, [reported](https://x.com/marty_kausas/status/2064739372625232068)
a $400K/yr Anthropic bill on seats (**≈ $220/dev-month**) about to jump to $1.4M/yr
(**≈ $780/dev-month**) because crossing 150 seats forces the Enterprise tier, where every token
bills at standard API rates. Our ≈ $150 is a bottom-up *moderate-usage* number; measured
startup-wide usage — parallel sessions, background agents, all-day runs — lands **1.5–5× higher**.

## Comparison by team size

Self-hosted at the 25% planning number (~100 devs/GPU, GPUs added as `ceil(devs / 100)`), API at
the ≈ $150/dev-month planning number. Rows are on-demand — multiply the self-hosted columns by
≈ 0.57 for spot:

| Team size | GPUs | Always-on ≈ $/dev-mo | Work-hours ≈ $/dev-mo | API ≈ $/dev-mo |
|---|---|---|---|---|
| 10 | 1 | $290 | $84 | $150 |
| 25 | 1 | $115 | $34 | $150 |
| 50 | 1 | $60 | $17 | $150 |
| 100 | 1 | $30 | $8 | $150 |
| 250 | 3 | $35 | $10 | $150 |

**Rules of thumb: one always-on GPU ≈ $2,900/mo ≈ the API bill of ~20 moderately active agent
developers. With scale-to-zero work-hours mode (≈ $840/mo), the break-even drops to ~5–10
developers.**

**Heavy-usage scenario (Pylon-anchored).** Model both sides consistently: all-day agent use pushes
the duty cycle toward 100%, so one GPU supports only its ~24 concurrent slots — self-hosted rises
to ≈ $120/dev-month always-on (≈ $35 in work-hours mode) while the measured API bill for that
cohort is ≈ $780/dev-month. Break-even falls to **~4 developers** (always-on) and self-hosting
runs ~6–20× cheaper at scale. One honest counterweight: heavy users may be heavy precisely
because they lean on frontier-model quality, which is where the 27B quality gap bites hardest.

*(For reference, subscription seats cap the API bill at flat rates — Cursor Pro/Pro+/Ultra
$20/$60/$200, Claude Pro/Max $20/$100/$200 per dev-month. The $100–200 seats bracket the ≈ $150
API planning number, so the break-even barely moves if seats are on the table. The cap has a
cliff, though: past 150 seats Anthropic's Enterprise tier stops including usage and bills every
token at standard API rates — the 3.5×-overnight jump Pylon hit.)*

## Caveats

- **Quality gap:** a 27B model vs a frontier model — cheaper per token isn't automatically cheaper
  per task if it takes more iterations to finish the same work.
- The softest API-side assumption is the cold-turn share (1 in 10–20): every pause longer than the
  ~5-minute cache TTL adds a ~$0.26 full-context re-write, so choppier usage raises the API bill.
  Providers with different cache multipliers (reads ≠ 0.1×, writes ≠ 1.25×) shift the math
  proportionally.
- These are rounded list prices and usage estimates; treat every number as ±2×.
- [`service_optimized.yaml`](service_optimized.yaml) autoscales 1→4 (always-on conservative case);
  the work-hours numbers use the shipped [`service_scale_to_zero.yaml`](service_scale_to_zero.yaml)
  plus the [`warmup.sh`](warmup.sh) cron.
- Spot prices float (the $2.27 is a us-west-2 snapshot) and preemptions interrupt in-flight
  requests for ~3 minutes. `g7e` on-demand capacity can also be tight in a single AZ —
  `PREFER_SPOT` plus cross-zone scaling has been the reliable combination in practice.
- To tighten the numbers for your org, capture one real workday of agent traffic and count turns,
  tokens per turn, and `Σ(request wall time) / session wall time` — no GPU needed.

## Pricing sources

[AWS G7e announcement](https://aws.amazon.com/blogs/aws/announcing-amazon-ec2-g7e-instances-accelerated-by-nvidia-rtx-pro-6000-blackwell-server-edition-gpus/) ·
[g7e.4xlarge pricing](https://www.devzero.io/instances/aws/g7e.4xlarge) ·
[Claude API pricing](https://claude.com/pricing) ·
[OpenAI API pricing](https://openai.com/api/pricing/) ·
[Cursor pricing](https://cursor.com/pricing) ·
[Pylon's seat-cliff post (X, 2026)](https://x.com/marty_kausas/status/2064739372625232068)

← Back: [Part 3 README](README.md) · Benchmarks: [`BENCHMARKS.md`](BENCHMARKS.md) · Overview: [top-level README](../README.md)
