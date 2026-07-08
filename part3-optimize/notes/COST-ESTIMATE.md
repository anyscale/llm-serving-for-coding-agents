# Cost Reduction Estimate: Self-Hosted GPU vs Seats and APIs

This is a rough planning estimate for the Part 3 coding-agent service. Treat the numbers as
directional, not accounting-grade. Prices are rounded list prices from July 2026.

## Summary

This is the high-level summary. For details, see [Core Assumptions](#core-assumptions),
[API Cost](#api-cost), [Autoscaling Capacity Model](#autoscaling-capacity-model),
[Team Savings View](#team-savings-view), [Work-Hours Mode](#work-hours-mode), and
[Caveats](#caveats).

Self-hosting is primarily a cost-reduction play. One `g7e.4xlarge` appears to support roughly
**24 average-length active cached sessions**, which should be treated as the per-GPU capacity unit.
For planning, use **~50 registered developers/GPU** as the safe sizing number. That leaves margin for
long prompts, heavy-tailed context histories, clustered work-hour usage, and congestion when many
developers ask the service to prefill or decode at the same time.

At that planning capacity, self-hosting costs roughly **$58/dev-month** always-on, or
**$17/dev-month** if the GPU only runs during work hours. A 100-developer team should therefore plan
for **2+ GPUs during busy periods**, with autoscaling adding replicas during bursts and scaling back
down when demand falls.

Commercial pricing comes in two scenarios, and the comparison should be made against both:

1. **Scenario 1 - Subscription seats, ~$200/dev-month.** A Claude Max 20x or Cursor Ultra seat
   caps an individual heavy user at about $200/month, with usage limits attached.
2. **Scenario 2 - Token-metered billing, ~$800/dev-month.** When usage bills per token, either via
   API keys or enterprise tiers past the seat cliff, real coding-agent bills land near
   $800/dev-month for active engineers. Pylon measured about $780.

| Self-hosted mode | GPU cost | Planning cost at 50 devs/GPU | Savings vs $200 seats | Savings vs $800 token bill |
|---|---:|---:|---:|---:|
| Always-on, on-demand | ~$2,900/mo | ~$58/dev-mo | ~71% | ~93% |
| Work-hours, on-demand | ~$840/mo | ~$17/dev-mo | ~92% | ~98% |

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
| Planning registered developers per GPU | ~50 |
| Input tokens per turn | ~70K |
| Output tokens per turn | ~150 |

The `~24` active-session estimate comes from average token length: FP8 KV measured about **6.53x**
256K-context concurrency, or roughly **1.7M cached tokens/GPU**. At `~70K` tokens per turn, that is
about 24 average-length sessions.

That `~24` number is an instantaneous capacity estimate, not a safe team-size estimate. A 25%
average developer duty cycle does not imply that 100 developers can be served without contention:
even with independent usage, 100 developers at 25% activity produces about 25 active sessions on
average, with materially higher p95 concurrency. Real usage is also correlated around work hours,
standups, reviews, incidents, and launch deadlines.

For planning, treat **50 registered developers/GPU** as the capacity assumption. This deliberately
keeps headroom for long prompts, unusually large cached histories, slow prefill bursts, and congestion
when many developers become active at the same time.

```text
active sessions per GPU = practical KV token capacity / average tokens per session
(6.53 * 262,144) / (70,000 + 150) = ~24

cost per developer = monthly GPU cost / developers per GPU
~$2,900 / ~50 = ~$58/dev-month
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

## Autoscaling Capacity Model

Autoscaling makes the capacity story more defensible by scaling GPUs with active concurrency instead
of assuming one GPU can always serve the whole team. The planning unit should be active cached
sessions per GPU:

```text
required GPUs at any moment = ceil(active sessions / ~24 sessions per GPU)
monthly cost = total GPU replica-hours * GPU hourly price
```

For example, if 100 developers produce 35 active sessions during a busy period, the service should
scale to 2 GPUs rather than trying to fit that burst onto one GPU:

```text
ceil(35 active sessions / 24 sessions per GPU) = 2 GPUs
```

When the burst ends, replicas can scale back down. During nights, weekends, or low-usage windows, the
deployment can scale to one GPU or potentially zero GPUs if cold-start latency is acceptable.

The main planning metric should therefore be **GPU replica-hours per month**, not just registered
developers per GPU. A 100-developer team should be modeled as a 2+ GPU deployment during busy periods,
even if it can scale down to fewer replicas during quiet periods. Autoscaling preserves much of the
cost advantage by adding GPUs only when concurrent demand requires them, but it does not change the
per-GPU capacity limit.

## Team Savings View

The savings story still holds, especially against token-metered billing, but it is more credible when
50 devs/GPU is the planning case.

| Registered devs/GPU | Interpretation | Always-on cost/dev-mo | Work-hours cost/dev-mo |
|---:|---|---:|---:|
| 25 | Near-continuous or heavy usage, little multiplexing | ~$116 | ~$34 |
| 50 | Planning case with headroom for long prompts and bursty usage | ~$58 | ~$17 |

For a 100-developer team, the capacity assumption changes how many GPU replicas are needed:

| Capacity assumption | GPUs for 100 devs | Always-on GPU cost | Savings vs $200 seats | Savings vs $800 token bill |
|---|---:|---:|---:|---:|
| 50 devs/GPU | 2 | ~$5.8K/mo | ~$14.2K/mo | ~$74.2K/mo |
| 25 devs/GPU | 4-5 | ~$11.6K-$14.5K/mo | ~$5.5K-$8.4K/mo | ~$65.5K-$68.4K/mo |

At 100 developers, the commercial monthly totals are:

- Subscription seats: **~$20K/month**.
- Token-metered billing: **~$80K/month**.
- Self-hosted base case at 50 devs/GPU: **~$5.8K/month** always-on, before work-hours or
  autoscaling scale-down effects.

So the base-case savings at 100 developers are:

```text
vs $200 seats, always-on:  $20,000 - $5,800 = ~$14,200/month saved
vs $800 tokens, always-on: $80,000 - $5,800 = ~$74,200/month saved
```

## Work-Hours Mode

Work-hours mode assumes the GPU runs about 10 hours/day for 21 weekdays:

```text
10 hours/day * 21 weekdays * ~$4/hr = ~$840/month
~$840 / ~50 developers = ~$17/dev-month
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
- **Capacity:** the ~24 active-session estimate is based on average context length. It should not be
  treated as an SLA capacity. Real coding-agent sessions are likely heavy-tailed: some sessions will
  carry much larger histories than 70K tokens, reducing effective concurrency. The 50-developer/GPU
  planning assumption is meant to leave room for these extreme cases. Measure p50/p90/p95 cached
  tokens per session, active sessions per work-hour, cache eviction rate, queueing latency, and
  cold-prefill frequency before raising the density.
- **Autoscaling:** autoscaling reduces under-provisioning risk by adding GPU replicas during peak
  concurrency, but it does not change the per-GPU capacity limit. It also has operational caveats:
  scale-up latency, cold starts, cache loss on new replicas, routing effects, and whether idle GPU
  nodes actually terminate. For planning, estimate total GPU replica-hours rather than assuming one
  GPU can always serve the full team.
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
