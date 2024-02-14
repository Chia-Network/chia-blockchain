from __future__ import annotations

import pathlib
import re


def check_shielding() -> int:
    exclude = {"mozilla-ca"}
    roots = [path.parent for path in pathlib.Path(".").glob("*/__init__.py") if path.parent.name not in exclude]

    count = 0
    for root in roots:
        for path in root.glob("**/*.py"):
            lines = path.read_text().splitlines()

            for line_index, line in enumerate(lines):
                line_number = line_index + 1

                this_match = re.search(r"^ *(async def [^(]*(close|stop)|(except|finally)\b)[^:]*:", line)
                if this_match is not None:
                    previous_line_index = line_index - 1

                    if previous_line_index >= 0:
                        previous_line = lines[line_index - 1]
                        ignore_match = re.search(r"^ *# shielding not required", previous_line)
                        if ignore_match is not None:
                            continue

                    next_line_index = line_index + 1
                    if next_line_index < len(lines):
                        next_line = lines[line_index + 1]
                        next_match = re.search(r"^ *with anyio.CancelScope\(shield=True\):", next_line)
                    else:
                        next_match = None
                    if next_match is None:
                        for def_line in reversed(lines[:line_index]):
                            def_match = re.search(r"^ *def", def_line)
                            if def_match is not None:
                                # not async, doesn't need to be shielded
                                break

                            async_def_match = re.search(r"^ *async def", def_line)
                            if async_def_match is not None:
                                count += 1
                                print(f"{path.as_posix()}:{line_number}: {line}")
                                break

    return count
