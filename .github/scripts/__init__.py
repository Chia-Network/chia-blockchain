"""Mark `.github/scripts` as a package for consumer linters.

Ruff INP001 flags non-shebang modules in a directory without `__init__.py`.
chia-blockchain selects that rule. This file is synced to
`.github/scripts/__init__.py`.

Entry points put their own directory on sys.path and import siblings as
top-level modules, so this file is never imported. `.github` is not a
Python identifier, so the directory is not a nested package of the
consumer repository root. Unittest discovery in this repository reads
`github_scripts_init.py`, not an `__init__.py` beside the canonical modules.
"""

from __future__ import annotations
