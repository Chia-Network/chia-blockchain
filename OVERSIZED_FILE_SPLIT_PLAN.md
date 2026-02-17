# Oversized File Split Plan

Tracking plan for splitting `.py` source files in `chia/` that exceed 1500 lines.

**Scope:** `chia/**` only (excluding `chia/wallet/` which is being removed, and `chia/_tests/`)
**Threshold:** >1500 lines
**Approach:** One file per PR, easiest first

## Completed

| #   | File                             | Lines | PR      | Notes                                                                                                            |
| --- | -------------------------------- | ----- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| 1   | `chia/full_node/weight_proof.py` | 1738  | This PR | Extracted ~1077 lines of standalone helper functions into `weight_proof_utils.py`. Class stays in original file. |

## Remaining (ordered by estimated difficulty)

### 2. `chia/daemon/server.py` — 1621 lines

- **Structure:** `WebSocketServer` class (1203 lines) + ~418 lines of utility functions and smaller classes
- **Split strategy:** Extract the ~10 standalone functions at the bottom (`daemon_launch_lock_path`, `service_launch_lock_path`, `launch_plotter`, `launch_service`, `kill_processes`, `kill_service`, `is_running`, `async_run_daemon`, `run_daemon`, `main`) plus helper classes (`PlotState`, `PlotEvent`, `Command`, `StatusMessage`) into `daemon_utils.py`. This brings `server.py` to ~1200 lines (the class itself) and creates a ~420 line utils file.
- **Difficulty:** Medium — the standalone functions are easy to move but the class itself is still large. A second pass could split the class further by grouping methods (e.g., plotter management, service management, keychain operations, websocket handling).

### 3. `chia/data_layer/data_store.py` — 1856 lines

- **Structure:** Single `DataStore` class (1778 lines)
- **Split strategy:** Group methods by concern:
  - Tree/node operations (insert, delete, upsert batches)
  - Proof generation methods
  - Subscription/mirror management
  - Root/history queries
    Extract one or more groups into mixin classes or standalone functions that take a `DataStore` connection parameter.
- **Difficulty:** Medium-Hard — single monolithic class, but methods are relatively independent database operations.

### 4. `chia/full_node/full_node_api.py` — 2070 lines

- **Structure:** `FullNodeAPI` class (1943 lines) + `tx_request_and_timeout` helper
- **Split strategy:** The class methods are protocol message handlers. Group by protocol:
  - Peer/connection handlers
  - Block-related handlers (request/respond blocks, compact proofs)
  - Transaction handlers
  - Timelord handlers
  - Wallet protocol handlers
    Extract groups into separate modules or mixin classes.
- **Difficulty:** Hard — tightly coupled class with shared state (`self.full_node`).

### 5. `chia/simulator/block_tools.py` — 2245 lines

- **Structure:** Likely a large `BlockTools` class with block generation helpers
- **Split strategy:** Separate block generation utilities from the main class. Helper functions for creating specific block types could move to a `block_tools_utils.py`.
- **Difficulty:** Hard — test infrastructure code with complex interdependencies.

### 6. `chia/full_node/full_node.py` — 3390 lines

- **Structure:** Large `FullNode` class
- **Split strategy:** Group by responsibility:
  - Sync logic (short sync, long sync, weight proof sync)
  - Block processing (receive block, add block, validation)
  - Mempool management
  - Peer management
  - Timelord interaction
    Each group could become a mixin or a separate module with functions.
- **Difficulty:** Very Hard — core class with extensive shared state and cross-cutting concerns. Largest file, save for last.

## Notes

- Files in `chia/wallet/` are excluded from this plan as that package is being removed.
- Test files (`chia/_tests/`) are excluded from this plan.
- `chia/cmds/wallet.py` (1896 lines) and `chia/cmds/wallet_funcs.py` (2004 lines) are wallet-specific CLI code and excluded.
