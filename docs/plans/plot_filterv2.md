# V2 Plot Filter

**Branch:** `v2-plot-filter`
**PR:** https://github.com/Chia-Network/chia-blockchain/pull/20414
**Spec:** [CHIP-48](https://github.com/Chia-Network/chips/blob/main/CHIPs/chip-0048.md)

---

## Summary

The V2 plot filter replaces the V1 grindable prefix-bits filter with a
deterministic, per-plot filter for PoS2 plots. This is a consensus-level
change that activates at `HARD_FORK2_HEIGHT`.

In V1, a plot passes the filter at a signage point when:

```python
filter_bits = sha256(plot_id + sub_slot_challenge + cc_signage_point)
```

Because `cc_signage_point` is not known until the signage point arrives, a
farmer cannot predict filter passage in advance. A fast plotter can exploit
that by grinding plot IDs that pass multiple consecutive signage points.

V2 fixes this by making filter passage predictable from already-known
sub-slot data. Each plot group passes according to its strength and a
deterministic position within a 16-signage-point window. The challenge is
derived from completed sub-slots, not from individual signage points.

This means:

- Plot grinding against newly-arrived signage points is removed.
- Farmers can know filter passage before the relevant signage point and can
  idle or spin down disks between expected passings.
- Sync does not need extra signage-point VDF proofs because the needed
  challenge data is already available from chain records.
- V2 plots always require a `filter_challenge`; there is no fallback to the
  V1 prefix-bits filter.

---

## Filter Formula

```python
def plot_id_check(plot_group_id, group_strength, meta_group, filter_challenge, challenge_index):
    mask = (1 << group_strength) - 1
    return hash(plot_group_id + filter_challenge) & mask == (challenge_index ^ meta_group) & mask
```

Implementation uses `sha256(...)[:4]` before masking. `group_strength` is
capped at `MAX_EFFECTIVE_PLOT_FILTER_BITS = 13` (the 8192 cap), so 32 bits is
sufficient.

### Terms

| Term               | Type      | Description                                                                   |
| ------------------ | --------- | ----------------------------------------------------------------------------- |
| `plot_group_id`    | `bytes32` | Hash of the V2 plot group identity.                                           |
| `plot_id`          | `bytes32` | Hash of `plot_group_id`, `plot_index`, and `meta_group`.                      |
| `plot_index`       | `uint16`  | Index of the plot within its plot group.                                      |
| `meta_group`       | `uint8`   | Decorrelation byte so different plot groups pass at different signage points. |
| `plot_strength`    | `uint8`   | Plot's absolute strength value.                                               |
| `min_strength`     | `int`     | Minimum valid plot strength for the schedule height.                          |
| `base_filter_bits` | `int`     | Network base plot-id filter bits at the schedule height.                      |
| `group_strength`   | `int`     | `min(base_filter_bits(height) + max(0, plot_strength - min_strength), 13)`.   |
| `filter_challenge` | `bytes32` | Challenge derived from completed sub-slot/end-of-slot data.                   |
| `challenge_index`  | `int`     | `signage_point_index % 16`, the position within the 16-SP window.             |

The "schedule height" used for `base_filter_bits`, `min_strength`, and
`max_strength` is `prev_transaction_block_height` — the height of the last
transaction block before the current signage point. It is used consistently
across verification (`verify_and_get_quality_string`), harvester filtering
(`challenge.last_tx_height`), and BlockTools proof selection, so farming and
validation cannot disagree around schedule boundaries.

### Identity Derivation

```text
plot_group_id = sha256(
    plot_strength:  u8,
    plot_pk:        G1Element,
    pool_info:      G1Element | bytes32,  # pool_pk or puzzle_hash
)

plot_id = sha256(
    plot_group_id:  bytes32,
    plot_index:     u16,
    meta_group:     u8,
)
```

---

## Filter Challenge

The current design uses completed sub-slot/end-of-slot data for
`filter_challenge`; it no longer uses individual signage points as the source
of the filter challenge.

Window mapping:

| Signage points | Filter challenge source                   | Approximate advance notice |
| -------------- | ----------------------------------------- | -------------------------- |
| `0-15`         | Penultimate completed sub-slot, `SS(n-2)` | About 10 minutes           |
| `16-63`        | Previous completed sub-slot, `SS(n-1)`    | About 2.5-7.5 minutes      |

During live operation, the full node gets the challenge from
`FullNodeStore.get_filter_challenge()`. During sync, validation derives the
same value with `get_filter_challenge_from_chain()` by walking
`BlockRecord.finished_challenge_slot_hashes`.

This removes the earlier sync gap. Peers do not need to send extra
signage-point VDF outputs or proofs for V2 filter validation.

---

## Strength And Schedule

Authoritative protocol-chat formula:

```text
applied_plot_id_filter = min(plot_filter * (2 ** (plot_strength - min_strength)), 8192)
```

In bit terms:

```text
effective_filter_bits = min(base_filter_bits + (plot_strength - min_strength), 13)
```

`min_strength` is both the validity floor and the zero point for filter scaling:
a plot at the minimum strength uses the network base plot filter. The effective
plot filter is capped at:

```text
8192 == 2**13
```

The protocol-chat schedule has two phases:

```text
Plot filter: 1024, min strength: 0
Plot filter: 512,  min strength: 0
Plot filter: 256,  min strength: 0
Plot filter: 128,  min strength: 0
Plot filter: 64,   min strength: 0
Plot filter: 64,   min strength: 1
Plot filter: 64,   min strength: 2
Plot filter: 64,   min strength: 3
...
```

The current branch implements the first kind of schedule, base plot-filter
reductions, but not the second kind, scheduled `min_strength` increases. In
current code `MIN_PLOT_STRENGTH` is a fixed consensus constant.

Current branch base-filter schedule starts at 512 and is reduced over time:

| Offset From `HARD_FORK2_HEIGHT` | Approx. Year | Base Filter Bits | Base Filter |
| ------------------------------- | ------------ | ---------------- | ----------- |
| 0                               | 2026         | 9                | 512         |
| 10,101,000                      | +~6 years    | 8                | 256         |
| 15,146,000                      | +~9 years    | 7                | 128         |
| 20,197,000                      | +~12 years   | 6                | 64          |
| 25,247,000                      | +~15 years   | 5                | 32          |
| 30,298,000                      | +~18 years   | 4                | 16          |
| 35,343,000                      | +~21 years   | 3                | 8           |
| 40,394,000                      | +~25 years   | 2                | 4           |
| 45,444,000                      | +~28 years   | 1                | 2           |
| 50,494,000                      | +~31 years   | 0                | 1           |

Implementation currently stores this as offsets relative to
`HARD_FORK2_HEIGHT`, so the hard fork height must be finalized before
activation. Scheduled `min_strength` offsets still need authoritative values
before they can be implemented.

Open questions for the protocol owner:

- **Starting base filter: 512 vs 1024.** The ticket and the protocol-chat
  schedule both start at 1024 (10 bits); the implemented `_BASE_FILTER_OFFSETS`
  starts at 512 (9 bits). Note the interaction with the cap: with min strength 0
  and base 1024, the 8192 cap is reached at strength 3 already.
- **`MAX_PLOT_STRENGTH = 17` is not ticket-driven.** Neither ticket defines a
  maximum strength; 17 is a branch decision that needs explicit sign-off.

---

## Protocol Flow

```text
Full Node                          Farmer                           Harvester
    |                                |                                  |
    |  NewSignagePoint               |                                  |
    |  (includes filter_challenge)   |                                  |
    |------------------------------->|                                  |
    |                                |  NewSignagePointHarvester2       |
    |                                |  (includes filter_challenge)     |
    |                                |--------------------------------->|
    |                                |                                  |
    |                                |        For each V2 plot:         |
    |                                |        passes_plot_filter_v2()   |
    |                                |                                  |
    |                                |        PartialProofsData         |
    |                                |<---------------------------------|
    |                                |                                  |
    |                                |  Solver -> Full proof            |
    |                                |  DeclareProofOfSpace             |
    |<-------------------------------|                                  |
```

### Data Availability

| Value              | Harvester Source                         | Full Node Source                                                |
| ------------------ | ---------------------------------------- | --------------------------------------------------------------- |
| `plot_group_id`    | `compute_plot_group_id(strength, plot_pk, pool_info)` | `compute_plot_group_id_from_pos(pos)`             |
| `meta_group`       | V2 plot params from prover               | `pos.meta_group`                                                |
| `plot_index`       | V2 plot params from prover               | `pos.plot_index`                                                |
| `filter_challenge` | Protocol message                         | `get_filter_challenge()` or `get_filter_challenge_from_chain()` |
| `challenge_index`  | `signage_point_index % 16`               | `signage_point_index % 16`                                      |
| `plot_strength`    | `prover.get_strength()`                  | `pos.param().strength_v2`                                       |

---

## Key Files

| File                                             | Role                                                           |
| ------------------------------------------------ | -------------------------------------------------------------- |
| `chia/types/blockchain_format/proof_of_space.py` | Filter logic, constants, base-filter schedule, identity derivation.       |
| `chia/full_node/full_node_store.py`              | `get_filter_challenge()` for live operation.                   |
| `chia/consensus/get_block_challenge.py`          | `get_filter_challenge_from_chain()` for sync validation.       |
| `chia/consensus/block_header_validation.py`      | Sync validation wiring.                                        |
| `chia/consensus/multiprocess_validation.py`      | Batch pre-validation wiring.                                   |
| `chia/full_node/full_node.py`                    | Populates `filter_challenge` in signage-point messages.        |
| `chia/full_node/full_node_api.py`                | Looks up `filter_challenge` for V2 proof verification.         |
| `chia/harvester/harvester_api.py`                | V2 filter dispatch, with no V1 fallback.                       |
| `chia/farmer/farmer_api.py`                      | Forwards `filter_challenge` and handles V2 partial proof flow. |
| `chia/protocols/farmer_protocol.py`              | `filter_challenge` field on `NewSignagePoint`.                 |
| `chia/protocols/harvester_protocol.py`           | `filter_challenge` field on `NewSignagePointHarvester2`.       |
| `chia/consensus/default_constants.py`            | Fixed `MIN_PLOT_STRENGTH=0`, `MAX_PLOT_STRENGTH=17`.           |
| `chia/plotting/prover.py`                        | `V2Prover` delegation to `chia_rs`.                            |
| `chia/simulator/block_tools.py`                  | Simulator V2 proof selection for test-chain generation.        |

### Dependency Chain

```text
chia-pos2 (Rust library)
    -> chia_rs (Python bindings)
    -> chia-blockchain
```

---

## Implementation Status

Done on the `v2-plot-filter` branch:

- `passes_plot_filter_v2()` implements the V2 filter formula.
- `compute_plot_group_id()` and `compute_plot_group_id_from_pos()` implement
  V2 identity derivation.
- `get_filter_challenge()` derives the live-operation filter challenge from
  sub-slot data.
- `get_filter_challenge_from_chain()` derives the sync-path filter challenge
  from `BlockRecord.finished_challenge_slot_hashes`.
- Farmer and harvester protocol messages carry `filter_challenge`.
- The harvester dispatches V2 plots through the V2 filter path.
- `V2Prover` delegates to the real `chia_rs` prover for `plot_index`,
  `meta_group`, and `strength`.
- Base filter reduction uses `_BASE_FILTER_OFFSETS`.
- Min/max strength come directly from the `MIN_PLOT_STRENGTH` /
  `MAX_PLOT_STRENGTH` constants (no schedule helpers until offsets are
  finalized).
- The effective V2 filter is capped at `8192` and strength scaling is relative
  to the current minimum plot strength.
- `MAX_PLOT_STRENGTH = 17` and fixed `MIN_PLOT_STRENGTH = 0` (per ticket: min
  strength begins at 0 and only rises via a future schedule).
- Sync validation is wired through `block_header_validation.py` and
  `multiprocess_validation.py`.
- Weight proofs skip the V2 filter check with `height_agnostic=True`.
- V2 plots are rejected if `filter_challenge` is unavailable.

---

## Remaining Gaps

### Must Fix Before Activation

| Gap                                | Files                                                                                                                                                                                       | Description                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Re-enable disabled consensus tests | `chia/_tests/blockchain/test_blockchain.py`, `chia/_tests/core/full_node/test_full_node.py`, `chia/_tests/weight_proof/test_weight_proof.py`, `chia/_tests/wallet/sync/test_wallet_sync.py` | 12+ tests are disabled with `limit_consensus_modes`; block tools wiring is now in place. |

### Cleanup And Follow-Up

| Gap                                  | Files                                                  | Description                                                               |
| ------------------------------------ | ------------------------------------------------------ | ------------------------------------------------------------------------- |
| Add V2 happy-path quality test       | `chia/_tests/core/custom_types/test_proof_of_space.py` | Add a V2 plot that passes the filter and produces a valid quality string. |
| Add scheduled min-strength updates   | `chia/types/blockchain_format/proof_of_space.py`       | Protocol chat describes holding plot filter at 64 while raising `min_strength`; `MIN_PLOT_STRENGTH` is a fixed constant until exact offsets are available. |
| Update RPC netspace calculation      | `chia/full_node/full_node_rpc_api.py`                  | Netspace estimation still uses V1 prefix bits.                            |
| Hook up plot params in plot creation | `chia/plotting/create_plots.py`                        | `plot_index` and `meta_group` are currently hardcoded to 0.               |
| Add V2 plot sync receiver support    | `chia/_tests/plot_sync/test_receiver.py`               | Effective plot size calculation does not account for V2.                  |
| Enable V2 prover tests               | `chia/_tests/plotting/test_prover.py`                  | Skipped until V2 test plots are available.                                |
| Finalize PoS quality formula         | `chia/consensus/pos_quality.py`                        | V2 expected plot size formula may change with the final plotter.          |

### Deferred To Separate PR

| Gap                           | Files   | Description                                                                                                |
| ----------------------------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| Move constants to chia_rs     | chia_rs | Move `FILTER_WINDOW_SIZE` and `_BASE_FILTER_OFFSETS` to `ConsensusConstants`.                              |
| Remove dead chia_rs constants | chia_rs | Remove obsolete V2 prefix-filter constants; current `chia_rs` still requires them in `ConsensusConstants`. |

---

## Test Commands

```bash
tools/pytest chia/_tests/core/custom_types/test_proof_of_space.py::TestV2PlotFilter -v
tools/pytest chia/_tests/core/full_node/stores/test_full_node_store.py::TestGetFilterChallenge -v
tools/pytest chia/_tests/core/custom_types/test_proof_of_space.py::TestComputePlotGroupId -v
tools/pytest chia/_tests/core/custom_types/test_proof_of_space.py -v
```

---

## References

- **CHIP-48:** https://github.com/Chia-Network/chips/blob/main/CHIPs/chip-0048.md
- **chia-pos2:** https://github.com/Chia-Network/chia-pos2
- **PR #20414:** https://github.com/Chia-Network/chia-blockchain/pull/20414
- **Task source:** `docs/plans/v2-plot-filter-tasks.md`
- **Historical completion plan:** `docs/plans/2026-03-31-v2-plot-filter-completion.md`
