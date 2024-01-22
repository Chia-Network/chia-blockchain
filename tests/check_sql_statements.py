#!/usr/bin/env python3
from __future__ import annotations

import sys
from subprocess import check_output
from typing import Dict, Set, Tuple

# check for duplicate index names


def check_create(sql_type: str, cwd: str, exemptions: Set[Tuple[str, str]] = set()) -> int:
    # the need for this change seems to come from the git precommit plus the python pre-commit environment
    # having GIT_DIR specified but not GIT_WORK_TREE.  this is an issue in some less common git setups
    # such as with worktrees, at least in particular uses of them.  i think that we could switch to letting
    # pre-commit provide the file list instead of reaching out to git to build that list ourselves.  until we
    # make time to handle that, this is an alternative to alleviate the issue.
    exemptions = {(cwd + "/" + file, name) for file, name in exemptions}
    lines = check_output(["git", "grep", f"CREATE {sql_type}"]).decode("ascii").split("\n")

    ret = 0

    items: Dict[str, str] = {}
    for line in lines:
        if f"CREATE {sql_type}" not in line:
            continue
        if line.startswith("tests/"):
            continue
        if "db_upgrade_func.py" in line:
            continue
        if not line.startswith(cwd):
            continue

        name = line.split(f"CREATE {sql_type}")[1]
        if name.startswith(" IF NOT EXISTS"):
            name = name[14:]
        name = name.strip()
        name = name.split()[0]
        name = name.split("(")[0]

        if name in items:
            # these appear as a duplicates, but one is for v1 and the other for v2
            if (line.split()[0][:-1], name) not in exemptions:
                print(f'duplicate {sql_type} "{name}"\n    {items[name]}\n    {line}')
                ret += 1

        items[name] = line

    return ret


ret = 0

ret += check_create("INDEX", "chia/wallet")
ret += check_create(
    "INDEX",
    "chia/full_node",
    {
        ("block_store.py", "is_fully_compactified"),
        ("block_store.py", "height"),
    },
)
ret += check_create("TABLE", "chia/wallet")
ret += check_create(
    "TABLE",
    "chia/full_node",
    {
        ("block_store.py", "sub_epoch_segments_v3"),
        ("block_store.py", "full_blocks"),
        ("coin_store.py", "coin_record"),
        ("hint_store.py", "hints"),
    },
)
sys.exit(ret)
