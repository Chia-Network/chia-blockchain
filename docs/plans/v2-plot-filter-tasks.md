# V2 Plot Filter - Remaining Tasks

**Branch:** `v2-plot-filter`
**PR:** https://github.com/Chia-Network/chia-blockchain/pull/20414
**Spec:** [CHIP-48](https://github.com/Chia-Network/chips/blob/main/CHIPs/chip-0048.md)

The overview/spec lives in `docs/plans/plot_filterv2.md`. This file only
tracks remaining work.

---

## Must Fix Before Activation

| Task                               | Files                                                                                                                                                                                       | Notes                                                                                    |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Re-enable disabled consensus tests | `chia/_tests/blockchain/test_blockchain.py`, `chia/_tests/core/full_node/test_full_node.py`, `chia/_tests/weight_proof/test_weight_proof.py`, `chia/_tests/wallet/sync/test_wallet_sync.py` | 12+ tests are disabled with `limit_consensus_modes`; block tools wiring is now in place. |

---

## Tests

| Task                              | Files                                                  | Notes                                                                     |
| --------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------- |
| Add V2 happy-path quality test    | `chia/_tests/core/custom_types/test_proof_of_space.py` | Add a V2 plot that passes the filter and produces a valid quality string. |
| Enable V2 prover tests            | `chia/_tests/plotting/test_prover.py`                  | Currently skipped until V2 test plots are available.                      |
| Add V2 plot sync receiver support | `chia/_tests/plot_sync/test_receiver.py`               | Effective plot size calculation does not account for V2.                  |

---

## Follow-Up Work

| Task                                    | Files                                 | Notes                                                            |
| --------------------------------------- | ------------------------------------- | ---------------------------------------------------------------- |
| Update RPC netspace calculation         | `chia/full_node/full_node_rpc_api.py` | Netspace estimation still uses V1 prefix bits.                   |
| Hook up V2 plot params in plot creation | `chia/plotting/create_plots.py`       | `plot_index` and `meta_group` are currently hardcoded to 0.      |
| Finalize V2 PoS quality formula         | `chia/consensus/pos_quality.py`       | V2 expected plot size formula may change with the final plotter. |

---

## Deferred To Separate PR

| Task                                   | Files   | Notes                                                                                                                                                              |
| -------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Move filter constants to chia_rs       | chia_rs | Move `FILTER_WINDOW_SIZE` and `_BASE_FILTER_OFFSETS` to `ConsensusConstants`.                                                                                      |
| Remove dead V2 prefix-filter constants | chia_rs | Remove `NUMBER_ZERO_BITS_PLOT_FILTER_V2` and `PLOT_FILTER_V2_FIRST/SECOND/THIRD_ADJUSTMENT_HEIGHT`; current `chia_rs` still requires them in `ConsensusConstants`. |
