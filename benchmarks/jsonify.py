from __future__ import annotations

import random
from time import perf_counter

from tests.util.test_full_block_utils import get_full_blocks

random.seed(123456789)


def main() -> None:
    total_time = 0.0
    counter = 0
    for block in get_full_blocks():
        start = perf_counter()
        block.to_json_dict()
        end = perf_counter()
        total_time += end - start
        counter += 1

    print(f"total time: {total_time:0.2f}s ({counter} iterations)")


if __name__ == "__main__":
    main()
