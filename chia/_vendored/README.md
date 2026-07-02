# Vendored third-party packages

This directory contains third-party packages that are vendored (copied) into the
`chia` package instead of being declared as external dependencies. Code here is
imported as `chia._vendored.<package>`.

Do not edit the vendored sources by hand. To upgrade, replace the package
directory wholesale with a new release and update the version recorded below.

## aiosqlite

- Upstream: https://github.com/omnilib/aiosqlite
- Version: 0.22.1
- Source: https://files.pythonhosted.org/packages/4e/8a/64761f4005f17809769d23e518d915db74e6310474e733e3593cfc854ef1/aiosqlite-0.22.1.tar.gz
- sha256: 043e0bd78d32888c0a9ca90fc788b38796843360c855a7262a532813133a0650
- License: MIT (see `aiosqlite/LICENSE`)

Only the `aiosqlite/` package directory and its `LICENSE` are vendored; the
upstream `tests/` directory is intentionally omitted. The package has no runtime
dependencies beyond the standard library.

### Upgrade steps

1. Download the new sdist from PyPI and verify its hash.
2. Replace `chia/_vendored/aiosqlite/` with the new `aiosqlite/` package dir plus
   its `LICENSE` (delete the bundled `tests/` dir).
3. Update the version/source/hash recorded above.
4. Run the DB tests and `mypy`/`ruff`.
