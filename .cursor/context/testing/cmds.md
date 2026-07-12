# Chia Commands Tests Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/_tests/cmds/` is the CLI contract test module. It primarily verifies that Click parsing, command helper dataclasses, config/root-path handling, RPC-client selection, wallet request construction, transaction output files, and user-facing text stay aligned with `chia/cmds/`. Most tests intentionally stop at the command/RPC boundary; they are not full wallet or node behavior tests unless they explicitly use service fixtures.

## When To Read This

Read this for CLI tests, command parser behavior, mocked RPC-client tests, command output expectations, transaction-output files, and command framework coverage. For CLI implementation context, also read `cmds.md`.

## Harness Boundaries

- `conftest.py` provides `get_test_cli_clients`, a module-scoped temporary Chia root with default config plus monkeypatches that replace `get_any_service_client`, `get_wallet_client`, and `cli_confirm` in both `chia.cmds.cmds_util` and the command modules that imported those functions directly. Tests using this fixture exercise the real CLI entrypoint while avoiding daemon/keychain/RPC processes.
- `cmd_test_utils.py` is the central mock-RPC harness. `TestRpcClient` records method calls, `TestRpcClients.get_client()` maps concrete RPC client classes to mutable fake clients, and command tests assert both rendered output and exact request dataclasses/arguments sent to fake RPC methods.
- `run_cli_command()` mutates `sys.argv` and invokes the top-level `chia` CLI with `--root-path`. It treats any non-zero `SystemExit` as failure and returns captured stdout. This means tests often fail through `AssertionError` wrapping Click output rather than directly through Click exceptions.
- Wallet command tests share deterministic fixtures from `wallet/test_consts.py`: fixed fingerprints, wallet ids, `bytes32` helpers, `STD_TX`, and `STD_UTX`. These values are part of the expected text/request-shape contract.
- Only a small minority of tests cross into live services: `test_cmd_framework.test_wallet_rpc_helper` uses `wallet_environments`, and `test_farm_cmd.test_farm_summary_command` uses farmer/harvester/simulator/wallet services. Treat those as integration tests with async convergence requirements, unlike the mock-RPC command tests.

## Command Framework Contracts

- `test_cmd_framework.py` is the specification for the newer class-based command system in `chia.cmds.cmd_classes` and `chia.cmds.cmd_helpers`. It verifies dataclass command wrapping, sync/async `run()` dispatch, type-hint-to-Click option generation, nested `command_helper` parsing, context injection, and rejection of unsupported/default-incompatible type shapes.
- `TransactionEndpoint` tests enforce that transaction endpoint subclasses use `@transaction_endpoint_runner`, preserve default option parity with older decorators, write returned `TransactionRecord`s through `TransactionsOut`, and convert `--valid-at/--expires-at` into `ConditionValidTimes`.
- `test_old_decorator_support` intentionally keeps old decorator functions (`coin_selection_args`, `tx_config_args`, `tx_out_cmd`) in sync with class-based helpers. If the legacy decorators are removed, this test is expected to be deleted rather than preserved with compatibility shims.
- `test_tx_config_args.py`, `test_timelock_args.py`, and `test_click_types.py` pin CLI conversion behavior for amounts, fees, addresses, bytes32 values, uint64 values, coin-selection config, reuse/new-address selection, and hidden timelock options. These are user-interface contracts and should not be loosened without matching CLI migration intent.

## RPC And Config Boundary

- `test_cmds_util.py` covers `get_any_service_client`: no-SSL test server use, friendly consumed `ResponseFailureError` output, traceback formatting, `consume_errors=False`, unknown client types without explicit ports, and unexpected exception consumption. These tests protect CLI error presentation as much as networking behavior.
- `test_peer.py` verifies service-name validation, connection table rendering, and missing config-section errors. Solver coverage matters because `solver` is configured differently from older services and may be absent from existing configs.
- `create_service_and_wallet_client_generators()` loads config from the temp root, derives default RPC ports from `node_config_section_names`, supports DataLayer's `fill_missing_services`, and patches modules that imported service helpers by name. New command modules that import `get_any_service_client` directly may need explicit monkeypatch coverage here.

## Wallet CLI Coverage

- `wallet/test_wallet.py` is a broad command-to-wallet-RPC contract suite: get transaction(s), show balances, send XCH/CAT, get address, clawback, delete unconfirmed transactions, derivation index, sign message, add token, make/take/cancel offers, and offer summaries. It asserts exact `wallet_request_types` objects, `TXConfig`, fee/mojo conversions, timelock propagation, CAT/NFT name resolution, royalty summary calls, and transaction bundle file output.
- `wallet/test_did.py`, `wallet/test_nft.py`, `wallet/test_vcs.py`, and `wallet/test_notifications.py` follow the same pattern for asset-specific subcommands. They do not prove DID/NFT/VC/notification wallet internals; they prove CLI parsing, ID/address conversion, RPC request construction, output text, `push` flags, fees, reuse-puzhash config, and `ConditionValidTimes`.
- Wallet command tests commonly subclass `TestWalletRpcClient` inside a single test to expose only the RPC methods under inspection. This keeps expected call logs precise; avoid moving behavior into a global fake unless multiple commands intentionally share the same RPC surface.
- Many assertions compare rich dataclass instances from `chia.wallet.wallet_request_types`. A failing equality usually means a CLI argument no longer maps to the same public RPC contract, not just an output formatting change.

## Other Command Areas

- `test_show.py` uses fake full-node RPC responses plus synthetic `FullBlock`/`TestBlockRecord` objects to check `chia show` output and RPC call ordering for chain state, fee estimates, height lookup, and block printing.
- `test_farm_cmd.py` is a real-service integration check for `farm summary`. It waits for harvester-to-farmer plot sync before hitting real RPC ports, then asserts stable sections of summary output with and without pool rewards.
- `test_daemon.py` isolates daemon startup/keyring behavior with mocks and a short-lived subprocess. It is sensitive to `sys.argv[0]`, keyring unlock messaging, and daemon process cleanup.
- `test_dev_gh.py` validates local argument/path checks for GitHub workflow dispatch. The real dispatch test is skipped and should stay isolated from ordinary CLI test runs unless CI/auth behavior is explicitly being tested.
- `test_sim.py` contains skipped simulator end-to-end command tests. They document intended simulator CLI flows but are not active safety coverage.
- `wallet/test_wallet_check.py` is pure logic coverage for `chia.cmds.check_wallet_db` gap/contiguous-used-address checks and wallet type parsing from DB rows.

## Change Guidance

- Pick the smallest harness matching the boundary: direct param type/helper calls for conversion logic, `CliRunner` for Click-only parsing, `get_test_cli_clients` for command-to-RPC contracts, and live service fixtures only when the command's behavior depends on real service state.
- For command-to-RPC tests, assert both stdout and the fake RPC call log. Output-only assertions can miss broken request payloads; call-log-only assertions can miss user-visible CLI regressions.
- When adding a new service/client command, update the fake client mapping or monkeypatches if the command imports helper functions directly. A real command may work while tests still hit an unpatched helper path.
- Keep fee and amount expectations explicit about units. `TransactionFeeParamType` applies a source-defined decimal-XCH fee cap, while generic `AmountParamType` produces `CliAmount` and converts later using wallet-specific mojo-per-unit.
- Preserve root-path isolation. Tests should use temp roots, `runner.isolated_filesystem()`, or explicit temp paths for config and transaction files; touching default roots is a flake and state-leak risk.
- Avoid raw sleeps in the few live-service tests. Use `time_out_assert` or existing service readiness checks because farm/daemon/wallet fixtures are timing-sensitive.

## Fragility Signals

- Direct imports of patch targets in command modules are easy to miss. If a command file does `from chia.cmds.cmds_util import get_wallet_client`, patching only `cmds_util` will not affect that module's local binding.
- CLI text assertions are intentionally brittle for public UX. If wording changes are deliberate, update the specific expected strings and keep request-shape assertions intact.
- Transaction file output uses `TransactionBundle` streamable bytes. Changes to `TransactionRecord` serialization or output-file wiring can break offline signing/push workflows even if stdout still looks correct.
- `ChiaCliContext.expected_prefix` caches address prefix during parameter conversion. Address tests that pass without config may be depending on this cache; be careful when moving address parsing earlier or outside Click context.
- The command framework is mid-transition between decorators and dataclass helpers. Do not add compatibility layers unless both old and new command styles are still meant to be supported.

## Source Pointers

- CLI test helpers and fixtures: `chia/_tests/cmds/cmd_test_utils.py`, `chia/_tests/cmds/conftest.py`.
- Command framework coverage: `chia/_tests/cmds/test_cmd_framework.py`, `chia/_tests/cmds/test_cmds_util.py`, `chia/_tests/cmds/test_click_types.py`.
- CLI implementation context: `chia/cmds/`.
