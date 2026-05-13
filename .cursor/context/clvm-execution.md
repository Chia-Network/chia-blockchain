# CLVM / Puzzle Execution — Deep Context

> Attach when touching puzzle execution, spend validation, generator logic,
> condition processing, or `chia/types/blockchain_format/`.

## Key files

| File                                                 | Role                                                |
| ---------------------------------------------------- | --------------------------------------------------- |
| `chia/consensus/condition_tools.py`                  | `pkm_pairs()` — extract AGG_SIG conditions          |
| `chia/consensus/generator_tools.py`                  | `get_block_header()` — strip generator from block   |
| `chia/consensus/get_block_generator.py`              | `get_block_generator()` — resolve generator refs    |
| `chia/consensus/cost_calculator.py`                  | `NPCResult` — name/puzzle/conditions result         |
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
- Legacy path: `create_block_generator()` serializes with `solution_generator_backrefs()`
- Alternative path: `create_block_generator2()` uses Rust `BlockBuilder`; opt-in today via
  `full_node.config["block_creation"] = 1` (see TODO in `full_node_api.py` to make it default)

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

**Location**: `chia/types/condition_opcodes.py`

Key conditions (from CLVM spend output):

| Opcode | Name                         | Effect                                    |
| ------ | ---------------------------- | ----------------------------------------- |
| 43     | `AGG_SIG_PARENT`             | Require signature with parent data        |
| 44     | `AGG_SIG_PUZZLE`             | Require signature with puzzle hash data   |
| 45     | `AGG_SIG_AMOUNT`             | Require signature with amount data        |
| 46     | `AGG_SIG_PUZZLE_AMOUNT`      | Require signature with puzzle+amount data |
| 47     | `AGG_SIG_PARENT_AMOUNT`      | Require signature with parent+amount data |
| 48     | `AGG_SIG_PARENT_PUZZLE`      | Require signature with parent+puzzle data |
| 49     | `AGG_SIG_UNSAFE`             | Require signature (no domain separation)  |
| 50     | `AGG_SIG_ME`                 | Require signature with coin data          |
| 51     | `CREATE_COIN`                | Create a new coin                         |
| 52     | `RESERVE_FEE`                | Declare minimum fee                       |
| 60     | `CREATE_COIN_ANNOUNCEMENT`   | Create announcement                       |
| 61     | `ASSERT_COIN_ANNOUNCEMENT`   | Assert announcement exists                |
| 62     | `CREATE_PUZZLE_ANNOUNCEMENT` | Create puzzle announcement                |
| 63     | `ASSERT_PUZZLE_ANNOUNCEMENT` | Assert puzzle announcement                |
| 64     | `ASSERT_CONCURRENT_SPEND`    | Assert another coin is spent              |
| 65     | `ASSERT_CONCURRENT_PUZZLE`   | Assert puzzle hash is spent               |
| 66     | `SEND_MESSAGE`               | Cross-coin messaging                      |
| 67     | `RECEIVE_MESSAGE`            | Cross-coin messaging                      |
| 70     | `ASSERT_MY_COIN_ID`          | Assert own coin ID                        |
| 71     | `ASSERT_MY_PARENT_ID`        | Assert parent coin ID                     |
| 72     | `ASSERT_MY_PUZZLEHASH`       | Assert own puzzle hash                    |
| 73     | `ASSERT_MY_AMOUNT`           | Assert own amount                         |
| 74     | `ASSERT_MY_BIRTH_SECONDS`    | Assert creation timestamp                 |
| 75     | `ASSERT_MY_BIRTH_HEIGHT`     | Assert creation height                    |
| 76     | `ASSERT_EPHEMERAL`           | Assert coin is ephemeral                  |
| 90     | `SOFTFORK`                   | Future-proof softfork condition           |

### Timelock conditions

| Opcode | Name                             | Effect                         |
| ------ | -------------------------------- | ------------------------------ |
| 80     | `ASSERT_SECONDS_RELATIVE`        | Min seconds since confirmation |
| 81     | `ASSERT_SECONDS_ABSOLUTE`        | Min timestamp                  |
| 82     | `ASSERT_HEIGHT_RELATIVE`         | Min blocks since confirmation  |
| 83     | `ASSERT_HEIGHT_ABSOLUTE`         | Min block height               |
| 84     | `ASSERT_BEFORE_SECONDS_RELATIVE` | Max seconds since confirmation |
| 85     | `ASSERT_BEFORE_SECONDS_ABSOLUTE` | Max timestamp                  |
| 86     | `ASSERT_BEFORE_HEIGHT_RELATIVE`  | Max blocks since confirmation  |
| 87     | `ASSERT_BEFORE_HEIGHT_ABSOLUTE`  | Max block height               |

---

## AGG_SIG conditions and replay protection

### `AGG_SIG_ME_ADDITIONAL_DATA`

Mainnet: `ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb`

Each AGG_SIG variant appends different additional data:

- `AGG_SIG_PARENT`: `hash(data + 43)`
- `AGG_SIG_PUZZLE`: `hash(data + 44)`
- `AGG_SIG_AMOUNT`: `hash(data + 45)`
- etc.

This provides replay protection across forks. Forks MUST change
`AGG_SIG_ME_ADDITIONAL_DATA` to prevent cross-chain replays.

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
