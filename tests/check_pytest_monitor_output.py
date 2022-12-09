#!/usr/bin/env python3
from __future__ import annotations

import sys

ret = 0

# example input line
# test_non_tx_aggregate_limits 0.997759588095738 1.45325589179993 554.45703125
for ln in sys.stdin:
    line = ln.strip().split()

    print(f"{float(line[1]) * 100.0: 8.1f}% CPU {float(line[2]):7.1f}s {float(line[3]): 8.2f} MB RAM  {line[0]}")
    limit = 800

    # until this can be optimized, use higher limits
    if "test_duplicate_coin_announces" in line[0]:
        limit = 2200
    elif (
        "test_duplicate_large_integer_substr" in line[0]
        or "test_duplicate_reserve_fee" in line[0]
        or "test_duplicate_large_integer_negative" in line[0]
        or "test_duplicate_large_integer" in line[0]
    ):
        limit = 1100

    if float(line[3]) > limit:
        print("   ERROR: ^^ exceeded RAM limit ^^ \n")
        ret += 1

if ret > 0:
    print("some tests used too much RAM")

sys.exit(ret)
