"""Mark `.github/scripts` as a package for consumer linters.

Ruff INP001 flags non-shebang modules in a directory without `__init__.py`.
chia-blockchain selects that rule. This file is synced to
`.github/scripts/__init__.py`.

Trusted loaders execute modules by file path and do not import this file.
`.github` is not a Python identifier, so the directory is not a nested
package of the consumer repository root. Unittest discovery in this
repository reads `github_scripts_init.py`, not an `__init__.py` beside the
canonical modules.
"""

from __future__ import annotations
