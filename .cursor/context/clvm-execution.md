# CLVM / Puzzle Execution — Deep Context

> Attach when touching puzzle execution, spend validation, generator logic,
> condition processing, or `chia/types/blockchain_format/`.

## Key files

| File                                                 | Role                                                |
| ---------------------------------------------------- | --------------------------------------------------- |
| `chia/consensus/condition_tools.py`                  | `pkm_pairs()` — extract AGG_SIG conditions          |
| `chia/consensus/generator_tools.py`                  | `get_block_header()` — strip generator from block   |
| `chia/consensus/get_block_generator.py`              | `get_block_generator()` — resolve generator refs    |
| `chia/consensus/condition_costs.py`                  | Condition opcode costs                              |
| `chia/types/blockchain_format/program.py`            | CLVM program wrapper                                |
| `chia/types/blockchain_format/serialized_program.py` | Lazy deserialization                                |
| `chia/types/blockchain_format/coin.py`               | `Coin(parent_id, puzzle_hash, amount)`              |
| `chia/types/condition_opcodes.py`                    | All condition opcode values                         |
| `chia/types/condition_with_args.py`                  | `ConditionWithArgs`                                 |
| `chia/types/generator_types.py`                      | `BlockGenerator`, `NewBlockGenerator`               |
| `chia/types/clvm_cost.py`                            | Cost constants                                      |
| `chia/full_node/mempool_manager.py`                  | `pre_validate_spendbundle()`, `is_clvm_canonical()` |
| `chia/wallet/conditions.py`                          | Condition construction for wallet spends            |
| `chia/wallet/puzzles/`                               | CLVM puzzle source files                            |

---

## Execution paths

### 1. Mempool validation (spend bundles)

```
SpendBundle → validate_clvm_and_signature() [Rust]
           → SpendBundleConditions
```

- Runs in thread pool (`MempoolManager.pool`)
- Flags: `get_flags_for_height_and_constants(peak.height) | MEMPOOL_MODE`
- Cost limit: `max_tx_clvm_cost` (half of `MAX_BLOCK_COST_CLVM`)

### 2. Block validation (generators)

```
BlockGenerator → run_block_generator() / run_block_generator2() [Rust]
             → SpendBundleConditions
```

- Generator refs resolved via `get_block_generator()` (up to 512 refs)
- Flags: `get_flags_for_height_and_constants(prev_tx_height)`
- Cost limit: `MAX_BLOCK_COST_CLVM` (11 000 000 000)

### 3. Block building (mempool → generator)

```
Mempool items → solution_generator_backrefs() [Rust] → generator program
```

- Combines spend bundles into a single block generator
- Uses back-references for compression
- Default path: `create_block_generator2()` uses Rust `BlockBuilder`, selected by `full_node.config["block_creation"] = 1` (the default). Legacy path `create_block_generator()` is opt-in via `block_creation = 0`. See `full_node_api.py` block-version selection.

---

## Resource limits

### Cost metering

Every CLVM operation has an associated cost. Total cost per block cannot
exceed `MAX_BLOCK_COST_CLVM = 11 000 000 000`.

### Generator byte cost

Each byte of generator program costs `COST_PER_BYTE = 12 000` CLVM cost
units, in addition to execution cost.

### Atom/pair bounds (mempool only)

After CLVM execution:

```python
if sbc.num_atoms > sbc.cost * 60_000_000 / MAX_BLOCK_COST_CLVM:
    reject  # too many atoms
if sbc.num_pairs > sbc.cost * 60_000_000 / MAX_BLOCK_COST_CLVM:
    reject  # too many pairs
```

This bounds memory usage relative to cost paid. At max cost, allows
60 million atoms or pairs.

### Generator ref list

`MAX_GENERATOR_REF_LIST_SIZE = 512` — max number of previous block generators
that can be referenced.

---

## Canonical serialization

**Location**: `mempool_manager.py:185`

### `is_clvm_canonical(clvm_buffer)`

Checks that a CLVM program uses shortest-form atom encoding:

- No unnecessary length prefix bytes
- No back-references (`0xFE` byte)
- No trailing garbage

### When enforced

Required for DEDUP-eligible spends. Without canonical form, identical
solutions could have different serializations, breaking dedup.

### `is_atom_canonical(clvm_buffer, offset)`

Validates a single atom's length prefix encoding. The CLVM format uses
variable-length prefixes (1-6 bytes) based on atom size. Each prefix
length has a minimum atom size threshold.

---

## Condition opcodes

Condition opcode byte values are a CLVM output ABI contract owned by `chia/types/condition_opcodes.py`; see `types.md` for the compatibility invariant. Read the enum directly for exact values rather than relying on a copied table, since renumbering or reusing a byte value changes consensus and wallet behavior.

Timelock conditions (`ASSERT_SECONDS_*`, `ASSERT_HEIGHT_*`, `ASSERT_BEFORE_*`) and `AGG_SIG_*` variants are interpreted by Rust validation and full-node/wallet code, not by the `ConditionWithArgs` dataclass. Semantic argument counts and domain-separation rules live with the validators.

---

## AGG_SIG conditions and replay protection

### `AGG_SIG_ME_ADDITIONAL_DATA`

Each network defines its `AGG_SIG_ME_ADDITIONAL_DATA` value (read it from the active constants, not a hard-coded mainnet value). Each AGG_SIG variant appends a different opcode-derived suffix to the additional data before signing, providing per-condition domain separation. Forks MUST change `AGG_SIG_ME_ADDITIONAL_DATA` to prevent cross-chain replay attacks.

---

## `MEMPOOL_MODE` flag

When set during CLVM execution:

- Enables stricter validation rules
- Rejects certain operations allowed in blocks but not in mempool
- Applied via `flags | MEMPOOL_MODE` in `pre_validate_spendbundle()`

---

## Block generator construction

### `get_block_generator()`

**Location**: `consensus/get_block_generator.py`

Resolves a block's generator and its references:

1. Block has `transactions_generator` (the program)
2. Block has `transactions_generator_ref_list` (height references)
3. For each ref, fetch the generator bytes from that block height
4. Return `BlockGenerator(program, ref_generators)`

### `solution_generator_backrefs()` [Rust]

Creates a block generator program from spend bundles using back-references
for compression. This is used during block creation from mempool items.
