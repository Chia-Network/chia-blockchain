# Chia Cmds Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/cmds/` is the user-facing CLI adapter layer. It owns command-line parsing,
local config/keychain setup, service/RPC client selection, terminal formatting,
and orchestration of daemon/service commands. It should not be treated as a
business-logic authority: most durable state, spend construction, consensus
validation, network behavior, and service lifecycles live in sibling modules and
are reached through config, keychain, daemon, and RPC boundaries.

## When To Read This

Read this for CLI command parsing, Click/dataclass command wiring, config/keychain setup from commands, RPC-client selection, transaction-output files, service start/stop commands, and terminal-facing behavior. For endpoint side effects, also read the concrete service context.

## Implementation Authority

- `chia.py` is the root Click command tree. It creates `ChiaCliContext`, records
  `root_path` and `keys_root_path`, configures the keyring root, optionally
  reads/caches a keyring passphrase, runs SSL permission checks, and registers
  every top-level command group.
- `ChiaCliContext` is the in-process CLI context authority. Commands read root
  paths, key paths, expected address prefix caches, RPC ports, and selected
  fingerprints from this object through Click's `ctx.obj`; avoid side channels
  for values that belong there.
- `cmd_classes.py` is the newer dataclass-command DSL. `@chia_command` freezes a
  command class, turns `option()` fields into Click options, recursively expands
  `@command_helper` fields, injects `ChiaCliContext` only for fields named
  `context`, and runs sync or async `run()` methods via `asyncio.run()`.
- Plain Click modules remain common. Many commands are thin parser wrappers that
  import their `*_funcs` implementation lazily and dispatch with `asyncio.run()`.
  This split is intentional for import cost and dependency isolation, but it
  means behavior can be split between a parser file and a sibling funcs file.
- `cmds_util.get_any_service_client()` is the generic RPC-client boundary for
  farmer, wallet, full node, harvester, data layer, simulator, and solver RPC
  clients. It loads config, chooses default ports, opens SSL or non-SSL clients,
  calls `healthz()`, and normalizes common connection/RPC errors for CLI output.
- `start_funcs.py` and `stop.py` cross into the daemon websocket authority. The
  CLI launches `chia run_daemon --wait-for-unlock`, unlocks the daemon keyring
  when needed, and starts/stops service names resolved from
  `chia.util.service_groups`.

## Command Execution Model

- Top-level options are applied before subcommand execution. Any code that needs
  the selected root path, key root, or cached address prefix should read
  `ChiaCliContext.set_default(ctx)` rather than re-resolving defaults.
- Async commands assume no running event loop in the CLI process. Both plain
  Click commands and dataclass commands generally use `asyncio.run()` at the
  command boundary; nested event-loop ownership belongs below RPC/service code,
  not inside command parsing.
- Parser modules should do CLI-specific validation and conversion only:
  command-line shape, Click option types, basic argument consistency, user
  prompts, file input/output, and terminal messages. Wallet, full-node, pool,
  data-layer, DB, and keychain semantics should stay in sibling modules or the
  `*_funcs.py` command implementation files.
- Several commands deliberately lazy-import heavy dependencies inside functions.
  Moving imports to module scope can change CLI startup time, optional dependency
  failures, and command help behavior.
- `rpc.py` is an escape-hatch client. It dynamically adds one command per
  service, accepts raw endpoint names plus JSON request data, and bypasses typed
  service-specific command helpers. Treat it as an operational tool, not the
  canonical API contract.

## Data Conversion Contracts

- `param_types.py` is the CLI conversion authority for fees, wallet amounts,
  addresses, `bytes32`, and `uint64`. Fees are decimal XCH strings capped at
  a source-defined XCH cap and converted to mojos; wallet amounts are stored as `CliAmount`
  until the target wallet unit is known.
- `AddressParamType` validates the selected network prefix for XCH/TXCH
  addresses by consulting `ChiaCliContext.expected_prefix` or loading
  `config.yaml`. Non-XCH address families are mapped through `AddressType`.
  Reusing it outside Click must account for possible config reads.
- `CMDTXConfigLoader` and `CMDCoinSelectionConfigLoader` bridge CLI amount/coin
  filters to wallet `TXConfig` and `CoinSelectionConfig`, autofilling with
  consensus constants and wallet config/fingerprint data.
- `tx_out_cmd()` and `TransactionEndpoint` are the transaction-output boundary.
  They add `--push/--no-push`, optional transaction-file output, coin-selection
  options, and absolute timelocks, then serialize `TransactionRecord` lists as a
  `TransactionBundle`. Commands that create wallet transactions should either use
  this path or explicitly document why their RPC shape is incompatible.
- `TransactionEndpoint.__post_init__()` enforces that subclasses decorate `run()`
  with `@transaction_endpoint_runner`; this keeps file-output handling from being
  silently skipped in dataclass-style transaction commands.

## Service And State Coupling

- Wallet commands are the widest surface. `wallet.py`, `coins.py`, `plotnft.py`,
  and `signer.py` parse user intent, while `wallet_funcs.py`, `coin_funcs.py`,
  and `plotnft_funcs.py` call `WalletRpcClient`, format balances/transactions,
  resolve wallet units, and handle offer/NFT/DID/VC/notification flows.
- `NeedsWalletRPC.wallet_rpc()` centralizes wallet RPC selection and login. If no
  fingerprint is supplied, `get_wallet()` may query the keychain, inspect the
  wallet's logged-in key and sync state, prompt the user, then call wallet
  `log_in()`. This is observable behavior, not a trivial client factory.
- Data-layer commands use `DataLayerRpcClient` through `data_funcs.get_client()`
  and can also log into the wallet by fingerprint. Some DataLayer transaction
  endpoints are not wired through the generic transaction-output decorators due
  to API peculiarities; observer-only/offline transaction behavior is therefore
  uneven across command groups.
- `init_funcs.py`, `configure.py`, and DB commands mutate local files. Config
  edits must use `lock_and_load_config()` for read-modify-write safety, and DB
  upgrade/backup/validate commands derive default paths from `full_node`
  selected-network config.
- Key commands operate on local key custody. `keys_funcs.py` unlocks the keyring,
  adds private or observer keys, displays derived keys/addresses, signs and
  verifies messages, and updates config reward targets through `init_funcs`.
  Treat `--show-mnemonic-seed` and file-based key input/output as sensitive
  terminal/file surfaces.
- Pool/plot NFT commands cross three authorities: wallet RPC, farmer RPC, and
  external pool HTTPS endpoints. Mainnet pool joins enforce HTTPS and pool
  protocol/relative-lock-height checks before wallet RPC submission.

## Fragility Hotspots

- Mixed command frameworks create duplication: old Click decorators, helper
  decorators in `cmds_util.py`, and dataclass helpers in `cmd_helpers.py` can
  express similar options with subtly different defaults, names, and timelock
  visibility.
- `get_any_service_client()` consumes many errors by printing and not re-raising
  unless `consume_errors=False`. Tests rely on this distinction; callers that
  need programmatic failure must opt out of consumption.
- CLI-facing validation is often user-experience oriented rather than complete
  domain validation. Do not rely on parser checks as wallet, consensus, or DB
  safety checks.
- Several commands use `sys.exit()`, `print()`, `input()`, and `click.Abort`
  directly. This is expected for terminal UX but makes library reuse and tests
  sensitive to stdout/stderr and prompting behavior.
- Address-prefix caching in `ChiaCliContext` is per Click invocation. Changes
  that bypass context can re-read config repeatedly or validate against the
  wrong network.
- DB upgrade and config commands perform irreversible-looking filesystem
  operations, but usually leave original DBs untouched or require explicit
  output paths. Preserve those guardrails and user confirmations when changing
  operational commands.

## Test And Audit Strategy

- CLI tests usually use `click.testing.CliRunner`, temporary Chia roots, and
  monkeypatched RPC client factories from `chia/_tests/cmds/cmd_test_utils.py`.
  Prefer mocked RPC clients for command parsing/dispatch tests over simulator
  harnesses unless the behavior truly depends on chain state.
- `test_cmd_framework.py` protects dataclass parsing, helper recursion, context
  injection, optional/sequence type handling, and transaction-endpoint
  invariants. Extend these when changing `cmd_classes.py` or `cmd_helpers.py`.
- `test_click_types.py` protects amount/fee/address/bytes32/uint64 conversion,
  including network-prefix validation and decimal precision. Any change to
  `param_types.py` should update these cases before broad wallet command tests.
- `test_cmds_util.py` protects RPC-client creation and error-consumption
  semantics. Changes to connection handling should test both consumed and
  propagated error modes.
- Wallet command tests assert RPC request shapes and terminal output using test
  RPC clients. When adding transaction-producing wallet commands, include both
  `--push/--no-push` and transaction-file behavior if the command participates in
  the standard transaction-output path.

## Source Pointers

- Root CLI and command context: `chia/cmds/chia.py`, `chia/cmds/cmd_classes.py`, `chia/cmds/cmd_helpers.py`.
- Common RPC/config/keychain helpers: `chia/cmds/cmds_util.py`, `chia/cmds/init_funcs.py`, `chia/cmds/configure.py`.
- Wallet and transaction command surfaces: `chia/cmds/wallet.py`, `chia/cmds/wallet_funcs.py`, `chia/cmds/coin_funcs.py`, `chia/cmds/param_types.py`.
- Service control commands: `chia/cmds/start_funcs.py`, `chia/cmds/stop.py`, `chia/cmds/rpc.py`.
