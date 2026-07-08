# Cost Reduction Estimate: Self-Hosted GPU vs Seats and APIs

This is a rough planning estimate for the Part 3 coding-agent service. Treat the numbers as
directional, not accounting-grade. Prices are rounded list prices from July 2026.

## Summary

This is the high-level summary. For details, see [Core Assumptions](#core-assumptions),
[API Cost](#api-cost), [Team Savings View](#team-savings-view),
[Work-Hours Mode](#work-hours-mode), and [Caveats](#caveats).

Self-hosting is primarily a cost-reduction play. At the planning capacity of about **100 developers
per GPU**, a self-hosted `g7e.4xlarge` costs roughly **$30/dev-month** always-on, or
**$8/dev-month** if the GPU only runs during work hours.

Commercial pricing comes in two scenarios, and the comparison should be made against both:

1. **Scenario 1 - Subscription seats, ~$200/dev-month.** A Claude Max 20x or Cursor Ultra seat
   caps an individual heavy user at about $200/month, with usage limits attached.
2. **Scenario 2 - Token-metered billing, ~$800/dev-month.** When usage bills per token, either via
   API keys or enterprise tiers past the seat cliff, real coding-agent bills land near
   $800/dev-month for active engineers. Pylon measured about $780.

| Self-hosted mode | GPU cost | Cost at 100 devs | Savings vs $200 seats | Savings vs $800 token bill |
|---|---:|---:|---:|---:|
| Always-on, on-demand | ~$2,900/mo | ~$30/dev-mo | ~85% | ~96% |
| Work-hours, on-demand | ~$840/mo | ~$8/dev-mo | ~96% | ~99% |

Break-even is small because the GPU is a shared fixed cost:

| Self-hosted mode | Break-even vs $200 seats | Break-even vs $800 token bill |
|---|---:|---:|
| Always-on, on-demand | ~15 devs | ~4 devs |
| Work-hours, on-demand | ~4 devs | ~1 dev |

## Core Assumptions

The self-hosted service runs on one `g7e.4xlarge` with one NVIDIA RTX PRO 6000 Blackwell
Server Edition GPU, which has **96 GB GPU memory**.

| Input | Planning value |
|---|---:|
| On-demand GPU price | ~$4.00/hr |
| Active sessions per GPU | ~24 |
| Developer duty cycle | ~25% |
| Developers per GPU | ~100 |
| Input tokens per turn | ~70K |
| Output tokens per turn | ~150 |

The `~24` active-session estimate comes from average token length: FP8 KV measured about **6.53x**
256K-context concurrency, or roughly **1.7M cached tokens/GPU**. At `~70K` tokens per turn, that is
about 24 average-length sessions. With bursty coding-agent usage, a 25% duty cycle turns those 24
active sessions into roughly 100 developers.

```text
active sessions per GPU = practical KV token capacity / average tokens per session
(6.53 * 262,144) / (70,000 + 150) = ~24

developers per GPU = active sessions / duty cycle
~24 / 25% = ~100 developers

cost per developer = monthly GPU cost / developers per GPU
~$2,900 / ~100 = ~$30/dev-month
```

## API Cost

The measured workload in [`BENCHMARKS.md`](BENCHMARKS.md) sends about **70K input tokens per turn**
because each turn includes the session history. Prompt caching helps, but repeated context still has
a cost.

At typical frontier-model rates:

- Cache read: about **$0.30/MTok**.
- Cache write: about **$3.75/MTok**.
- Output: about **$15/MTok**.
- Cache expiry: about **5 idle minutes**.

A warm turn costs about **$0.04**. A cold turn, or a turn after cache expiry, costs about **$0.26**.
With one cold turn every 10-20 turns, the blended estimate is about **$0.05/turn**.

```text
~2,000-4,000 turns/month * ~$0.05/turn = ~$100-200/dev-month
planning floor = ~$150/dev-month
heavy-user planning number = ~$800/dev-month
```

Self-hosting avoids per-token cache charges. vLLM prefix-cache hits and writes are not billed; KV
blocks are only evicted under memory pressure.

## Team Savings View

This table uses the planning assumption of about 100 developers per GPU and on-demand GPU pricing.
Negative savings mean the team is too small to beat that commercial baseline in that self-hosting
mode.

| Team size | GPUs | Seats cost | Token-billing cost | Always-on GPU cost | Savings vs seats | Savings vs token bill |
|---|---:|---:|---:|---:|---:|---:|
| 10 | 1 | ~$2.0K/mo | ~$8.0K/mo | ~$2.9K/mo | ~-$0.9K/mo | ~$5.1K/mo |
| 25 | 1 | ~$5.0K/mo | ~$20.0K/mo | ~$2.9K/mo | ~$2.1K/mo | ~$17.1K/mo |
| 50 | 1 | ~$10.0K/mo | ~$40.0K/mo | ~$2.9K/mo | ~$7.1K/mo | ~$37.1K/mo |
| 100 | 1 | ~$20.0K/mo | ~$80.0K/mo | ~$2.9K/mo | ~$17.1K/mo | ~$77.1K/mo |
| 250 | 3 | ~$50.0K/mo | ~$200.0K/mo | ~$8.7K/mo | ~$41.3K/mo | ~$191.3K/mo |

Work-hours mode improves the savings if the min-replica-0 deployment actually terminates the GPU node:

| Team size | GPUs | Work-hours GPU cost | Savings vs seats | Savings vs token bill |
|---|---:|---:|---:|---:|
| 10 | 1 | ~$0.8K/mo | ~$1.2K/mo | ~$7.2K/mo |
| 25 | 1 | ~$0.8K/mo | ~$4.2K/mo | ~$19.2K/mo |
| 50 | 1 | ~$0.8K/mo | ~$9.2K/mo | ~$39.2K/mo |
| 100 | 1 | ~$0.8K/mo | ~$19.2K/mo | ~$79.2K/mo |
| 250 | 3 | ~$2.5K/mo | ~$47.5K/mo | ~$197.5K/mo |

At 100 developers, the monthly totals are:

- Subscription seats: **~$20K/month**.
- Token-metered billing: **~$80K/month**.
- Self-hosted: **~$2.9K/month** always-on, or **~$840/month** during work hours.

So the savings at 100 developers are:

```text
vs $200 seats, always-on:   $20,000 - $2,900 = ~$17,100/month saved
vs $800 tokens, always-on:  $80,000 - $2,900 = ~$77,100/month saved
vs $200 seats, work-hours:  $20,000 - $840 = ~$19,200/month saved
vs $800 tokens, work-hours: $80,000 - $840 = ~$79,200/month saved
```

## Work-Hours Mode

Work-hours mode assumes the GPU runs about 10 hours/day for 21 weekdays:

```text
10 hours/day * 21 weekdays * ~$4/hr = ~$840/month
~$840 / ~100 developers = ~$8/dev-month
```

The work-hours setup uses [`service-work-hours.yaml`](../service-work-hours.yaml),
[`schedule-work-hours-warmup.yaml`](../schedule-work-hours-warmup.yaml), and
[`warmup.sh`](../warmup.sh).

Important caveat: replica scale-down to zero worked in testing, but the **GPU node did not always
terminate** because the CPU router could keep the only worker type alive. Treat work-hours cost as a
target until the cluster nodes page confirms the `g7e` node terminates after about 35 idle minutes.

Spot pricing is intentionally excluded from this estimate. It can be useful for experiments or
interruptible batch workloads, but preemption is a poor fit for stable interactive serving because it
can interrupt active sessions, discard KV cache, and add cold-start latency.

## Caveats

- **Model quality:** Qwen compares Qwen3.6-27B with Claude Opus 4.5, but real savings depend on whether
  it completes the same coding-agent work with acceptable extra turns. The quality case is that
[Qwen positions Qwen3.6-27B as comparable to Claude Opus 4.5](https://qwen.ai/blog?id=qwen3.6-27b),
but teams should still validate it on their own coding-agent workload.
- **Duty cycle:** heavier usage pushes self-hosted cost toward ~$120/dev-month always-on because one
  GPU supports closer to 24 continuously active sessions, not ~100 bursty developers.
- **GPU choice:** these estimates are benchmarked for `g7e.4xlarge`, which has one NVIDIA RTX PRO 6000
  Blackwell Server Edition GPU with 96 GB GPU memory. Redo the benchmark before applying the same math
  to other GPUs. For larger teams or heavier concurrent usage, higher-end GPUs such as B200 or B300 may
  be a better fit; they can support larger KV capacity and features such as NVFP4 KV cache, which can
  serve more concurrent requests and more users per GPU.
- **Cache behavior:** Anthropic-style token-metered APIs can expire prompt-cache entries after about
  5 minutes by default, causing the next request to pay for another full-context cache write. In
  vLLM/Ray Serve LLM, prefix/KV cache is instead tied to live replica memory and routing; it can be
  lost after replica restarts, scale-to-zero, memory pressure, or routing a request to a different
  replica.
- **Work-hours mode:** savings depend on the GPU node actually terminating.
- **Spot capacity:** spot instances are not included because preemption can make interactive serving
  unreliable.

## Sources

[AWS G7e announcement](https://aws.amazon.com/blogs/aws/announcing-amazon-ec2-g7e-instances-accelerated-by-nvidia-rtx-pro-6000-blackwell-server-edition-gpus/) |
[g7e.4xlarge pricing](https://www.devzero.io/instances/aws/g7e.4xlarge) |
[Claude API pricing](https://claude.com/pricing) |
[OpenAI API pricing](https://openai.com/api/pricing/) |
[Cursor pricing](https://cursor.com/pricing) |
[Pylon seat-cliff post](https://x.com/marty_kausas/status/2064739372625232068) |
[Qwen3.6-27B launch post](https://qwen.ai/blog?id=qwen3.6-27b)

Back: [Part 3 README](../README.md) | Benchmarks: [`BENCHMARKS.md`](BENCHMARKS.md) | Overview:
[top-level README](../../README.md)
