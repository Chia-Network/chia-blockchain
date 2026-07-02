# V2 Plot Strength Benchmark Notes

## Goal

Investigate whether V2 plot strength affects block production frequency in `BlockTools`.

The expected protocol property is that, when all plots in a run have the same strength, stronger plots should not produce blocks less frequently in a way that incentivizes everyone to create minimum-strength plots.

## Pre-Alignment Hypothesis

Before aligning to the ticket, the `BlockTools` path appeared to apply the V2 filter with probability roughly:

```text
1 / 2 ** (base_filter_bits + plot_strength)
```

In simulator `test_constants`, `NUMBER_ZERO_BITS_PLOT_FILTER_V2 == 0`, so this becomes:

```text
1 / 2 ** plot_strength
```

The pilot results suggested higher-strength plots pass the filter and produce eligible qualities much less frequently.

## Pilot Setup

- Repeatable script: `tools/benchmarks/v2_plot_strength.py`
- Note: the script now uses ticket-aligned effective filter bits. The measurements below were collected before that alignment.
- Example command:

```bash
tools/py tools/benchmarks/v2_plot_strength.py --strengths 2,8 --challenges 100000 --plots 4
```

- Constants based on `chia.simulator.block_tools.test_constants`
- Overrides:
  - `HARD_FORK2_HEIGHT = 0`
  - `SOFT_FORK9_HEIGHT = 0`
  - `MIN_PLOT_STRENGTH = 2`
  - `MAX_PLOT_STRENGTH = 17`
  - `NUMBER_ZERO_BITS_PLOT_FILTER_V2 = 0`
  - `DIFFICULTY_STARTING = 1024`
- `NUM_SPS_SUB_SLOT = 16`
- `SP_INTERVAL_ITERS = 64`
- Each successful run used 4 real V2 plots of a single strength.

## Harness Notes

Initial manual `BlockTools` scripts failed or stalled for harness reasons before useful measurements:

- Creating `BlockTools` without `TempKeyring` repeatedly tried to connect to the daemon keychain.
- Creating plots manually without `bt.add_plot_directory(bt.plot_dir)` caused plot refresh to assert because `expected_plots` was populated but the plot manager loaded zero plots.
- After fixing those harness issues, high-strength runs reproduced the stall behavior.

## Block Generation Pilot

Target was 20 blocks per strength, with a time cap.

| Strength | Loaded Plots | Blocks Produced | Timed Out | Elapsed Seconds | Empty Slot Gaps | Total Finished Sub Slots | Max Finished Sub Slots On One Block |
|---:|---:|---:|:---:|---:|---:|---:|---:|
| 2 | 4 | 31 | no | 21.711 | 308 | 353 | 66 |
| 8 | 4 | 7 | yes | 68.822 | 1618 | 1779 | 546 |
| 16 | 4 | 0 | yes/stalled | >150 | n/a | n/a | n/a |

Strength 16 did not reach block generation. Isolated tracing showed the run reached `keys ready`, then stalled on the first `new_plot2(..., strength=16)`.

## Challenge-Level Measurement

This bypassed full block creation and counted filter passes, returned qualities, and eligible qualities for real V2 plots.

| Strength | Challenges | Plot Checks | Expected Filter Passes | Actual Filter Passes | Qualities | Eligible Qualities | Eligible Per Challenge |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 10,000 | 40,000 | 10,000.0 | 10,041 | 10,222 | 46 | 0.0046 |
| 8 | 10,000 | 40,000 | 156.25 | 155 | 162 | 2 | 0.0002 |
| 2 | 100,000 | 400,000 | 100,000.0 | 100,258 | 100,549 | 484 | 0.00484 |
| 3 | 100,000 | 400,000 | 50,000.0 | 49,990 | 48,386 | 236 | 0.00236 |
| 8 | 100,000 | 400,000 | 1,562.5 | 1,547 | 1,467 | 9 | 0.00009 |

Per-plot filter passes:

| Strength | Plot 0 | Plot 1 | Plot 2 | Plot 3 |
|---:|---:|---:|---:|---:|
| 2 | 2450 | 2553 | 2490 | 2548 |
| 8 | 36 | 42 | 38 | 39 |
| 2 | 24,889 | 25,222 | 24,906 | 25,241 |
| 3 | 12,241 | 12,611 | 12,601 | 12,537 |
| 8 | 367 | 387 | 378 | 415 |

Per-read and per-quality ratios from the 100,000-challenge run:

| Strength | Qualities / Filter Pass | Eligible / Quality | Eligible / Filter Pass |
|---:|---:|---:|---:|
| 2 | 1.0029 | 0.00481 | 0.00483 |
| 3 | 0.9679 | 0.00488 | 0.00472 |
| 8 | 0.9483 | 0.00613 | 0.00582 |

## Post-Filter-Alignment Measurement

After changing the effective V2 filter bits to:

```text
min(base_filter_bits + (plot_strength - MIN_PLOT_STRENGTH), 13)
```

the same challenge-level benchmark reports:

| Strength | Effective Filter Bits | Challenges | Plot Checks | Expected Filter Passes | Actual Filter Passes | Qualities | Eligible Qualities | Eligible Per Challenge |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0 | 10,000 | 40,000 | 40,000.0 | 40,000 | 40,046 | 223 | 0.0223 |
| 3 | 1 | 10,000 | 40,000 | 20,000.0 | 19,974 | 19,460 | 99 | 0.0099 |

Clean 100,000-challenge rerun after the same alignment:

| Strength | Effective Filter Bits | Challenges | Plot Checks | Expected Filter Passes | Actual Filter Passes | Qualities | Eligible Qualities | Eligible Per Challenge |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0 | 100,000 | 400,000 | 400,000.0 | 400,000 | 400,818 | 2,109 | 0.02109 |
| 3 | 1 | 100,000 | 400,000 | 200,000.0 | 200,216 | 192,597 | 994 | 0.00994 |
| 8 | 6 | 100,000 | 400,000 | 6,250.0 | 6,294 | 6,106 | 34 | 0.00034 |

Per-read and per-quality ratios:

| Strength | Qualities / Filter Pass | Eligible / Quality | Eligible / Filter Pass |
|---:|---:|---:|---:|
| 2 | 1.00115 | 0.00557 | 0.00558 |
| 3 | 0.97427 | 0.00509 | 0.00496 |

Per-read and per-quality ratios from the clean 100,000-challenge rerun:

| Strength | Qualities / Filter Pass | Eligible / Quality | Eligible / Filter Pass |
|---:|---:|---:|---:|
| 2 | 1.00205 | 0.00526 | 0.00527 |
| 3 | 0.96195 | 0.00516 | 0.00496 |
| 8 | 0.97013 | 0.00557 | 0.00540 |

The filter read-rate is now relative to the fixed `MIN_PLOT_STRENGTH`, but the
eligible-per-read rate still does not compensate for the lower read rate of a
stronger plot in this simulator setup.

## Interpretation

The 10,000-challenge strength 2 vs strength 8 run showed about 23x fewer eligible qualities for strength 8:

```text
0.0046 / 0.0002 = 23
```

The 100,000-challenge run showed about 54x fewer eligible qualities for strength 8:

```text
0.00484 / 0.00009 = 53.78
```

This is consistent with the filter pass probability shrinking with strength. The measured filter pass counts match the expected filter-pass counts closely:

- Strength 2 expected 10,000, observed 10,041.
- Strength 8 expected 156.25, observed 155.
- Strength 2 expected 100,000, observed 100,258.
- Strength 8 expected 1,562.5, observed 1,547.

That points to the predictable filter as the primary source of the frequency skew in this pilot.

## Pre-Alignment Root-Cause Read

The observed skew followed directly from the pre-alignment implementation:

```python
group_strength = calculate_base_plot_filter_bits(height, constants) + plot_strength
```

and:

```python
mask = (1 << group_strength) - 1
passes = hash(plot_group_id + filter_challenge) & mask == target & mask
```

This gives each plot a filter pass probability of:

```text
1 / 2 ** (base_filter_bits + plot_strength)
```

With simulator `test_constants`, `base_filter_bits == 0`, so strength 8 passes the filter about `2 ** (8 - 2) == 64` times less often than strength 2.

The quality/iteration path does not currently compensate for this. `calculate_iterations_quality()` divides by `_expected_plot_size(size, constants)`, and `_expected_plot_size()` uses only `constants.PLOT_SIZE_V2` for V2 plots:

```python
k = constants.PLOT_SIZE_V2
return uint64((2**k) * (k + 1.46) / 8)
```

It does not scale expected plot size by `plot_strength`.

One-file plot size checks also did not show a compensating physical size increase:

| Strength | Plot Size Parameter | File Size Bytes | Create Seconds |
|---:|---:|---:|---:|
| 2 | 20 | 2,810,906 | 0.266 |
| 8 | 20 | 2,829,185 | 4.429 |

That means, in the pre-alignment local setup, higher strength was much slower to create and much less likely to produce eligible qualities, while the consensus-side expected-size calculation treated it like the same-size plot.

The protocol-author question "base strength vs one above it" points to the same issue:

| Strength | Eligible / Challenge | Eligible / Filter Pass |
|---:|---:|---:|
| 2 | 0.00484 | 0.00483 |
| 3 | 0.00236 | 0.00472 |

Strength 3 was read about half as often as strength 2, but it did not beat difficulty about twice as often once read. Its per-read success rate was effectively the same. That suggests the difficulty/expected-size side was not adjusting for the filter read-rate reduction.

## Open Questions

- What is the authoritative schedule for future `min_strength` increases? The
  protocol-chat model keeps the base plot filter at 64 and then raises
  `min_strength`, but the current branch only has a fixed `MIN_PLOT_STRENGTH`.
- Should the difficulty/expected-size path compensate for lower read frequency
  when `plot_strength > min_strength`?
- Why does `create_v2_plots(..., strength=16)` stall locally? This blocks direct high-strength `BlockTools` chain experiments.
- Should the benchmark count distinct signage-point attempts inside `get_consecutive_blocks()` directly instead of inferring empty slots from `finished_sub_slots`?

## Next Experiment

Instrument `BlockTools.get_pospaces_for_challenge()` or a local benchmark wrapper to record, per strength:

- signage-point challenge attempts
- filter passes
- qualities returned
- eligible qualities under `required_iters < sp_interval_iters`
- selected block proofs
- finished sub-slot gaps

This should make 10,000-block chains unnecessary for early diagnosis and avoid long stalls when high-strength plots rarely qualify.
