# Chia SSL Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/ssl/` is the certificate material and permission hygiene layer for Chia's local config root. It does not build network connections itself; it provisions trust roots and node certificates that `chia/server/`, `chia/rpc/`, and `chia/daemon/` turn into mutual-TLS contexts.

## When To Read This

Read this for certificate generation, public/private CA material, SSL file permissions, Chia root SSL layout, daemon/RPC certificate trust, and service certificate provisioning. For connection-time TLS behavior, also read `server.md`.

## Implementation Authority

- `create_ssl.py` is the provisioning authority. It creates `config/ssl/`, installs the bundled Chia public CA, creates or imports the user's private CA, and generates per-service private/public cert/key pairs under the paths expected by `config.yaml`.
- `ssl_check.py` is the filesystem-permission authority. It discovers configured cert/key paths, verifies platform-supported POSIX modes, reports unsafe files, and implements `chia init --fix-ssl-permissions`.
- The bundled `chia_ca.crt`/`chia_ca.key` are the public peer-network CA material. The generated `private_ca.crt`/`private_ca.key` are local/user trust material used for authenticated service relationships and daemon/RPC access.
- `chia/server/server.py`, not `chia/ssl/`, decides which CA/cert pair is used for each node type and calculates peer/node ids from the certificate fingerprint.

## Trust Roots And Certificate Classes

- There are two parallel trust domains. Public certs are signed by the bundled Chia CA and are used for ordinary public peer connections. Private certs are signed by the user's private CA and are used where the peer must be one of the user's trusted services.
- Private certs are generated for `full_node`, `wallet`, `farmer`, `harvester`, `timelord`, `crawler`, `data_layer`, `daemon`, and `solver`. Public certs are generated for `full_node`, `wallet`, `farmer`, `introducer`, `timelord`, `data_layer`, and `solver`.
- `ChiaServer.create()` encodes the operational matrix: harvesters use private certs as clients; harvester/farmer/wallet/data_layer servers require private-CA client certs; other peer servers use the public Chia CA. Changing generation lists or config paths without updating this matrix can silently break service startup or peer admission.
- Daemon and RPC traffic use daemon private certs with the private CA. This is a local/admin trust boundary, distinct from public peer TLS.
- Peer identity is the SHA-256 fingerprint of the TLS certificate selected by the server layer. Regenerating a service cert changes its node id and affects duplicate/self-connection detection.

## Provisioning Contracts

- `create_all_ssl(root_path)` assumes the default config path convention under `root_path / "config" / "ssl"`. It removes legacy `trusted.key`/`trusted.crt`, ensures `ssl/` and `ssl/ca/`, writes the bundled Chia CA, then generates private and public node certs.
- Passing `private_ca_crt_and_key` imports an existing private CA before node cert generation. If private CA files already exist on disk, they are reused. If either private CA file is missing, a new CA is created and all private node certs are regenerated from it.
- Public node cert generation uses `overwrite=False`; existing public cert/key pairs survive normal `create_all_ssl()` runs. Private generation follows the caller's `overwrite` argument, defaulting to replacement.
- `node_certs_and_keys` is an injection hook for tests and packaged fixtures. It is keyed by node name then cert prefix (`"private"`/`"public"`) and bypasses generated cert creation only when both `"crt"` and `"key"` are present.
- `write_ssl_cert_and_key()` unlinks before replacing and opens files with `O_CREAT | O_EXCL` plus explicit modes. Preserve this pattern when changing writes; SSL key material must not briefly inherit permissive umask-derived modes.

## Permission Model

- Default cert mode is `0o644`; default key mode is `0o600`. Certs may be world-readable but must not be group/other writable or executable. Keys must not grant any group/other permissions.
- Permission checks are skipped on Windows/Cygwin because ACL support is not implemented. Do not treat a successful no-op on those platforms as proof that files are protected.
- `get_all_ssl_file_paths()` reads configured paths from `config.yaml` with `fill_missing_services=True`, then appends the bundled Mozilla CA cert. Missing config keys are reported but do not abort the scan.
- Missing files are ignored by permission verification because nonexistent files cannot be dangerously permissive. Startup failures for missing certs occur later when TLS contexts load cert chains.
- `check_ssl()` warns but does not exit; `fix_ssl()` attempts `chmod` on files reported by the same verifier and reports whether anything changed or failed.

## Consumer Coupling

- `chia.server.ssl_context` is only a path resolver. It mirrors the nested config layout and returns root-relative paths for public/private service certs and CAs.
- `ssl_context_for_server()` and `ssl_context_for_client()` live in `chia/server/server.py`. They call `verify_ssl_certs_and_keys()`, load cert chains, require peer certificates, disable hostname checking, and use CA files to validate the opposite side.
- Server contexts require the source-defined default TLS minimum. The daemon may explicitly loosen its context via `daemon_allow_tls_1_2`; that exception belongs to daemon-local compatibility, not the general peer TLS policy.
- `chia_init()` creates default config before `create_all_ssl()`. Migration and `chia init -c <ca-dir>` copy CA files into `config/ssl/ca`, fix copied file permissions, and rerun certificate provisioning.
- Tests commonly generate ad hoc certs with `generate_ca_signed_cert()` and then select `private_ssl_ca_paths()` or `chia_ssl_ca_paths()` to assert which trust domain should accept the connection.

## Fragility Hotspots

- Highest-risk edits: changing node-name lists, altering public/private overwrite behavior, changing config key paths, broadening key permissions, or moving CA selection logic into `chia/ssl/` without updating `ChiaServer.create()`.
- Regenerating the private CA invalidates every private cert issued by the old CA. This can break farmer/harvester, daemon/RPC, wallet, and data-layer trust relationships across machines.
- Public CA material is bundled in source and written into user config. Treat changes to `chia_ca.crt`/`chia_ca.key` as network-wide compatibility changes, not local initialization details.
- The generated end-entity cert subject/SAN is generic (`Chia`, `chia.net`) and hostname verification is disabled in Chia's peer contexts. Security depends on CA trust and certificate fingerprint identity, not DNS-name matching.
- Permission path coverage is hand-maintained in `CERT_CONFIG_KEY_PATHS` and `KEY_CONFIG_KEY_PATHS`. Adding new SSL config entries requires adding them there or `check_ssl`/`fix_ssl` will not protect them.

## Source Pointers

- Certificate and CA provisioning: `chia/ssl/create_ssl.py`.
- SSL file permission checks and repair: `chia/ssl/ssl_check.py`.
- Connection-time SSL context selection: `chia/server/server.py`, `chia/server/ssl_context.py`.
