# V2 Plot Filter

## How It Works

V2 plots use a **predictable filter** — passage is known 1 SP in advance.
This allows HDD spin-down, prevents grinding, and uses `meta_group` to
decorrelate filter passage across plots.

### Formula

```
passes = (effective_filter == target)

effective_filter = sha256(plot_group_id + filter_challenge)[:4] & mask
target           = (challenge_index ^ meta_group) & mask
mask             = (1 << group_strength) - 1
challenge_index  = signage_point_index % 16
group_strength   = BASE_PLOT_FILTER + plot_strength
```

### Identity Derivation

```
plot_group_id = sha256(strength || plot_pk || pool_info)
plot_id       = sha256(plot_group_id || plot_index || meta_group)
```

`ProofOfSpace.compute_plot_id()` in chia_rs implements `plot_id`.
We reimplemented `plot_group_id` in Python — verified to match chia_rs.

### Constants

| Constant             | Value | Description                                        |
| -------------------- | ----- | -------------------------------------------------- |
| `FILTER_SP_LOOKBACK` | 4     | SPs before window start to sample filter_challenge |
| `FILTER_WINDOW_SIZE` | 16    | SPs per window (4 windows per subslot)             |
| `BASE_PLOT_FILTER`   | 0     | TODO: confirm with R&D                             |

### filter_challenge scoping

filter_challenge is **fixed for each 16-SP window**, not per-SP.
All SPs in the same window share the same filter_challenge.

```
Windows per subslot (64 SPs):
  [0-15]  → filter_challenge = SP hash at (0  - 4) = SP 60 of prev subslot
  [16-31] → filter_challenge = SP hash at (16 - 4) = SP 12
  [32-47] → filter_challenge = SP hash at (32 - 4) = SP 28
  [48-63] → filter_challenge = SP hash at (48 - 4) = SP 44
```

### Data Flow

```
Full Node                        Farmer                         Harvester
    |                               |                               |
    | NewSignagePoint               |                               |
    | (+ filter_challenge)          |                               |
    |------------------------------>|                               |
    |                               | NewSignagePointHarvester2     |
    |                               | (+ filter_challenge)          |
    |                               |------------------------------>|
    |                               |                               |
    |                               |              _plot_passes_filter()
    |                               |              V2: passes_plot_filter_v2()
    |                               |                               |
```

---

## Current API State (chia_rs)

### Available on ProofOfSpace (full node side)

| Field/Method            | Available | Notes             |
| ----------------------- | --------- | ----------------- |
| `pos.meta_group`        | Yes       | uint8 from wire   |
| `pos.plot_index`        | Yes       | uint16 from wire  |
| `pos.strength`          | Yes       | uint8 from wire   |
| `pos.version`           | Yes       | uint8 from wire   |
| `pos.compute_plot_id()` | Yes       | Canonical plot_id |

### Available on Prover (harvester side)

| Method                    | Available | Notes                             |
| ------------------------- | --------- | --------------------------------- |
| `Prover.get_strength()`   | Yes       |                                   |
| `Prover.plot_id()`        | Yes       |                                   |
| `Prover.get_memo()`       | Yes       |                                   |
| `Prover.get_meta_group()` | **No**    | Needed for `V2Prover.get_param()` |
| `Prover.get_plot_index()` | **No**    | Needed for `V2Prover.get_param()` |

### V2Prover.get_param() — the single remaining gap

```python
# Current (hardcoded 0s):
PlotParam.make_v2(0, 0, self._prover.get_strength())

# Once Prover exposes the values:
PlotParam.make_v2(self._prover.get_plot_index(), self._prover.get_meta_group(), self._prover.get_strength())
```

`meta_group` and `plot_index` are stored in the V2 plot file header
by chia-pos2. The Rust `Prover` reads the file but doesn't expose
these fields to Python yet.

---

## What's Done

| #   | Component                                                        | Status |
| --- | ---------------------------------------------------------------- | ------ |
| 1   | `passes_plot_filter_v2()` — core filter function                 | ✅     |
| 2   | `compute_plot_group_id()` — `sha256(strength \|\| pk \|\| pool)` | ✅     |
| 3   | `get_filter_challenge()` — per-window, 4-SP lookback             | ✅     |
| 4   | Protocol wiring (`filter_challenge` on messages)                 | ✅     |
| 5   | Full node populates `filter_challenge` in SP broadcasts          | ✅     |
| 6   | Farmer forwards `filter_challenge` to harvesters                 | ✅     |
| 7   | Harvester V2 dispatch in `_plot_passes_filter()`                 | ✅     |
| 8   | Full node verification via `pos.meta_group`                      | ✅     |
| 9   | Tests (filter function, group_id, filter_challenge)              | ✅     |

---

## What's Left

### 1. Expose `meta_group` and `plot_index` from Prover

Three repos need changes:

#### a) chia-pos2 (crates.io: `chia-pos2`)

The `Prover` struct already reads `index` and `meta_group` from the
plot file header and stores them as private fields. Just add getters:

```rust
// src/lib.rs, inside impl Prover { ... }
pub fn get_meta_group(&self) -> u8 {
    self.meta_group
}

pub fn get_plot_index(&self) -> u16 {
    self.index
}
```

Bump crate version and publish.

#### b) chia_rs (`wheel/src/api.rs`)

Add two methods to the `#[pymethods] impl Prover` block:

```rust
pub fn get_meta_group(&self) -> u8 {
    self.0.get_meta_group()
}

pub fn get_plot_index(&self) -> u16 {
    self.0.get_plot_index()
}
```

Update `chia-pos2` dependency version in `Cargo.toml`.

#### c) chia-blockchain (`chia/plotting/prover.py`)

One-line change in `V2Prover.get_param()`:

```python
return PlotParam.make_v2(
    self._prover.get_plot_index(),
    self._prover.get_meta_group(),
    self._prover.get_strength(),
)
```

### 2. Confirm BASE_PLOT_FILTER value (R&D)

Currently 0. The Jira ticket says `group_strength = filter + strength`,
implying the filter portion may be nonzero. Need R&D to confirm the
production value.

### 3. Run full test suite

Verify all changes compile and pass once merge conflict is resolved
and dependencies are consistent.

---

## Files Changed

| File                    | What                                                            |
| ----------------------- | --------------------------------------------------------------- |
| `proof_of_space.py`     | `passes_plot_filter_v2()`, `compute_plot_group_id()`, constants |
| `full_node_store.py`    | `get_filter_challenge()`                                        |
| `full_node.py`          | Populate filter_challenge in SP broadcasts                      |
| `harvester_api.py`      | V2 filter dispatch in `_plot_passes_filter()`                   |
| `farmer_protocol.py`    | `filter_challenge` field on `NewSignagePoint`                   |
| `harvester_protocol.py` | `filter_challenge` field on `NewSignagePointHarvester2`         |
| `farmer_api.py`         | Forward filter_challenge to harvesters                          |
