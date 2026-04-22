#!/usr/bin/env python3
"""
Build a wallet ``RequestCoinState`` (same shape as ``attack.py``), serialize to bytes,
deserialize with ``from_bytes``, and print timings.

Uses ``time.perf_counter()`` (wall time). Large ``--coin-ids`` uses a lot of RAM.

  cd ~/source/SEC-559 && source venv/bin/activate
  python bench_request_coin_state_roundtrip.py --coin-ids 200000
"""

from __future__ import annotations

import argparse
import gc
import sys
import time

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.protocols.wallet_protocol import RequestCoinState
from chia_rs.sized_bytes import bytes32


def main() -> None:
    p = argparse.ArgumentParser(description="Benchmark RequestCoinState bytes() and from_bytes().")
    p.add_argument("--coin-ids", type=int, default=50_000, help="Number of synthetic coin ids (default: 50000).")
    p.add_argument(
        "--deserialize-repeat",
        type=int,
        default=1,
        metavar="N",
        help="Run from_bytes() N times on the same blob (default: 1). Each run allocates a new object.",
    )
    p.add_argument("--gc-between", action="store_true", help="Run gc.collect() between deserialize repeats.")
    args = p.parse_args()

    if args.coin_ids < 0:
        sys.exit("--coin-ids must be non-negative")
    if args.deserialize_repeat < 1:
        sys.exit("--deserialize-repeat must be >= 1")

    print(f"coin_ids={args.coin_ids:,}", flush=True)

    t0 = time.perf_counter()
    payload_ids = [bytes32(i.to_bytes(32, "big")) for i in range(args.coin_ids)]
    t1 = time.perf_counter()
    print(f"build coin_id list:     {t1 - t0:8.3f}s", flush=True)

    t0 = time.perf_counter()
    req = RequestCoinState(payload_ids, None, DEFAULT_CONSTANTS.GENESIS_CHALLENGE, False)
    t1 = time.perf_counter()
    print(f"RequestCoinState(...):  {t1 - t0:8.3f}s", flush=True)

    t0 = time.perf_counter()
    data = bytes(req)
    t1 = time.perf_counter()
    print(f"bytes(req) serialize: {t1 - t0:8.3f}s  ({len(data):,} bytes)", flush=True)

    # Drop Python references to the huge list inside req so peak memory is closer to blob + one decode.
    del req
    del payload_ids
    gc.collect()

    max_items = 200_000

    for i in range(args.deserialize_repeat):
        if args.gc_between and i:
            gc.collect()
        t0 = time.perf_counter()
        _decoded = RequestCoinState.from_bytes(data)
        t1 = time.perf_counter()
        print(f"from_bytes decode #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={args.coin_ids:,})", flush=True)

        t0 = time.perf_counter()
        count = len(_decoded.coin_ids)
        t1 = time.perf_counter()
        print(f"get length #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={count:,})", flush=True)

        t0 = time.perf_counter()
        sliced = _decoded.coin_ids
        del sliced[max_items:]
        t1 = time.perf_counter()
        print(f"del list (slice) #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={len(sliced):,})", flush=True)

        t0 = time.perf_counter()
        dedup_list = list(dict.fromkeys(sliced))
        t1 = time.perf_counter()
        print(f"deduplicate list #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={len(dedup_list):,})", flush=True)

        del _decoded

    print(f"\n--- with list_limits={{coin_ids: {max_items:,}}} ---", flush=True)

    for i in range(args.deserialize_repeat):
        if args.gc_between and i:
            gc.collect()
        t0 = time.perf_counter()
        _decoded = RequestCoinState.from_bytes(data, list_limits={"coin_ids": max_items})
        t1 = time.perf_counter()
        print(f"from_bytes limited #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={len(_decoded.coin_ids):,})", flush=True)

        t0 = time.perf_counter()
        dedup_list = list(dict.fromkeys(_decoded.coin_ids))
        t1 = time.perf_counter()
        print(f"deduplicate list #{i + 1}: {t1 - t0:8.3f}s  (coin_ids={len(dedup_list):,})", flush=True)

        del _decoded

    print("done.", flush=True)


if __name__ == "__main__":
    main()

