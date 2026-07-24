# Bugbot Review Guidance

Use the repository context map before reporting issues that depend on
cross-file invariants. Prefer the relevant context document over reasoning from
a narrow diff alone. Start with `.cursor/context/INDEX.md` when unsure.

## Context Routing

Before reviewing a changed file, identify the subsystem and read the matching
context document:

| Changed area                                                   | Read first                             |
| -------------------------------------------------------------- | -------------------------------------- |
| `chia/consensus/**`, block validation, difficulty, SSI, reorgs | `.cursor/context/consensus.md`         |
| `chia/full_node/**`, sync, batch validation, node state        | `.cursor/context/full-node.md`         |
| `chia/full_node/mempool*.py`, fee logic, spend admission       | `.cursor/context/mempool.md`           |
| `chia/server/**`, peer connections, rate limits                | `.cursor/context/server.md`            |
| `chia/protocols/**`, wire messages                             | `.cursor/context/protocols.md`         |
| `chia/apis/**`, API stub metadata                              | `.cursor/context/apis.md`              |
| `chia/types/**`, shared types, serialization boundary          | `.cursor/context/types.md`             |
| `chia/wallet/**`                                               | `.cursor/context/wallet.md`            |
| CLVM, generators, puzzles, conditions                          | `.cursor/context/clvm-execution.md`    |
| `chia/farmer/**`                                               | `.cursor/context/farmer.md`            |
| `chia/harvester/**`                                            | `.cursor/context/harvester.md`         |
| `chia/timelord/**`                                             | `.cursor/context/timelord.md`          |
| `chia/plotting/**`, `chia/plot_sync/**`                        | `.cursor/context/plotting.md`          |
| `chia/pools/**`                                                | `.cursor/context/pools.md`             |
| `chia/daemon/**`                                               | `.cursor/context/daemon.md`            |
| `chia/data_layer/**`                                           | `.cursor/context/data-layer.md`        |
| `chia/rpc/**`                                                  | `.cursor/context/rpc.md`               |
| `chia/ssl/**`                                                  | `.cursor/context/ssl.md`               |
| `chia/simulator/**`                                            | `.cursor/context/simulator.md`         |
| `chia/solver/**`                                               | `.cursor/context/solver.md`            |
| `chia/cmds/**`                                                 | `.cursor/context/cmds.md`              |
| `chia/util/**`                                                 | `.cursor/context/util.md`              |
| Root config, build scripts, workflows, tooling                 | `.cursor/context/repo-tooling.md`      |
| Cross-cutting or security-sensitive changes                    | `.cursor/context/global-invariants.md` |

If multiple areas are touched, read each matching context document and check
the interaction between their invariants. If a suspected issue contradicts the
context, verify the full path before reporting it.
