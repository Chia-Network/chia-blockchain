# Chia Test Patterns

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

## Layered Assertions

Use layered assertions instead of a single final check:

1. **Immediate invariants** — object created, response success, expected fields present.
2. **Eventual behavior** — `time_out_assert(...)` for async convergence.
3. **Mempool checks** — `mempool_manager.get_spendbundle(...)`, `assert_sb_in_pool(...)`.
4. **Wallet transitions** — `process_pending_states(...)` with `WalletStateTransition`.
5. **Failure paths** — `pytest.raises(...)` with explicit error matching.
6. **Log assertions** — `caplog` for protocol/service side effects.

## Module-by-Module Test Setup Map

| Module             | Typical Setup                                                            | Blocks                                                         | Transaction Path                                                                                   | Assertion Style                                                               |
| ------------------ | ------------------------------------------------------------------------ | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `blockchain`       | `bt`, `empty_blockchain`, `two_nodes`                                    | `get_consecutive_blocks`, `add_block`, `add_blocks_in_batches` | `WalletTool.generate_signed_transaction`, protocol `send_transaction`, in-block `transaction_data` | direct consensus result checks, `pytest.raises`, occasional `time_out_assert` |
| `clvm`             | no network harness, or `sim_and_client`                                  | `SpendSim.farm_block`                                          | `sim_client.push_tx`                                                                               | direct CLVM/coin-store assertions, `pytest.raises`                            |
| `cmds`             | `CliRunner`, `get_test_cli_clients`, temp config roots                   | usually none                                                   | mocked RPC client calls                                                                            | output assertions, parse/validation errors                                    |
| `core`             | mixed: `one_node_one_block`, `simulator_and_wallet`, data-layer fixtures | heavy use of `get_consecutive_blocks`, farming APIs            | wallet-generated spends, protocol `send_transaction`/`respond_transaction`                         | heavy `time_out_assert`, mempool/state assertions, `caplog`, `pytest.raises`  |
| `db`               | `DBConnection`/`PathDBConnection` fixtures                               | none                                                           | none                                                                                               | concurrency/transactionality assertions, `pytest.raises`                      |
| `farmer_harvester` | `farmer_one_harvester*`, `harvester_farmer_environment`                  | minimal                                                        | protocol message flow                                                                              | service-state `time_out_assert`, `caplog`                                     |
| `fee_estimation`   | mostly mempool/unit harness                                              | minimal farming                                                | small generated spend bundles                                                                      | direct estimator state assertions                                             |
| `generator`        | pure generator/CLVM tests                                                | none                                                           | none                                                                                               | deterministic program output/cost assertions                                  |
| `harvester`        | `harvester_farmer_environment` + test plots                              | `default_400_blocks` for signage data                          | harvester protocol interactions                                                                    | `time_out_assert`, mock peer assertions                                       |
| `pools`            | pure puzzle unit tests and wallet/simulator integration                  | farming + reorg in integration                                 | wallet RPC and framework tx processing                                                             | `process_pending_states`, `time_out_assert`, `pytest.raises`                  |
| `simulation`       | `simulator_and_wallet`, full system fixture                              | high-level simulator farming/reorg                             | wallet-generated spends                                                                            | heavy `time_out_assert`, mempool/coin-store confirmations                     |
| `wallet`           | `wallet_environments` (primary), simulator fixtures                      | frequent farming/reorg                                         | wallet action scopes, wallet RPC                                                                   | `process_pending_states`, `time_out_assert`, mempool checks                   |
| `weight_proof`     | pre-generated block fixtures + `BlockchainMock`                          | `get_consecutive_blocks` for edge chains                       | none                                                                                               | proof validity/fork point assertions                                          |

## Checklist

- Harness matches behavior under test.
- Async convergence uses `time_out_assert`, not raw sleeps.
- Wallet behavior uses `process_pending_states` where practical.
- Mempool and confirmation asserted as separate steps.
- Failure paths use `pytest.raises` with explicit error matching.
