# Bugbot Review Guidance

Use the repository context map before reporting issues that depend on
cross-file invariants. Prefer the relevant context document over reasoning from
a narrow diff alone.

## Context Routing

Before reviewing a changed file, identify the subsystem and read the matching
context document:

| Changed area                                                             | Read first                             |
| ------------------------------------------------------------------------ | -------------------------------------- |
| `chia/consensus/**`, block validation, difficulty, SSI, reorgs           | `.cursor/context/consensus.md`         |
| `chia/full_node/**`, sync, batch validation, node state                  | `.cursor/context/full-node.md`         |
| `chia/full_node/mempool*.py`, fee logic, spend admission                 | `.cursor/context/mempool.md`           |
| `chia/server/**`, `chia/protocols/**`, peer connections, rate limits     | `.cursor/context/networking.md`        |
| `chia/wallet/**`                                                         | `.cursor/context/wallet.md`            |
| CLVM, generators, puzzles, conditions, `chia/types/blockchain_format/**` | `.cursor/context/clvm-execution.md`    |
| Cross-cutting or security-sensitive changes                              | `.cursor/context/global-invariants.md` |

If multiple areas are touched, read each matching context document and check
the interaction between their invariants. If a suspected issue contradicts the
context, verify the full path before reporting it.
