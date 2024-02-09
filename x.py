from __future__ import annotations

import pathlib
import re

regexp = r"^ *(async def [^(]*(close|stop)|(except|finally)\b)[^:]*:[^\n]*\n(?! *with anyio.CancelScope\(shield=True)"
# regexp = r"^ *(async def [^(]*(close|stop)|(except|finally)\b)"
# regexp = r"^ *async def"

# matches = []
# # TODO: get them all
# for root in ["chia", "tests"]:
#     root = pathlib.Path(root)
#     for path in root.glob("**/*.py"):
#         content = path.read_text()
#         matches.extend(re.findall(regexp, content, flags=re.MULTILINE))
#
# for match in matches:
#     print(match)


count = 0
# TODO: get them all
for root in [pathlib.Path("chia"), pathlib.Path("tests")]:
    for path in root.glob("**/*.py"):
        lines = path.read_text().splitlines()

        for line_index, line in enumerate(lines):
            line_number = line_index + 1

            this_match = re.search(r"^ *(async def [^(]*(close|stop)|(except|finally)\b)[^:]*:", line)
            if this_match is not None:
                # TODO: handle first and last line
                previous_line = lines[line_index - 1]
                next_line = lines[line_index + 1]

                ignore_match = re.search(r"^ *# shielding not required", previous_line)
                if ignore_match is not None:
                    continue

                next_match = re.search(r"^ *with anyio.CancelScope\(shield=True\):", next_line)
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

print(f"{count} concerns found")
