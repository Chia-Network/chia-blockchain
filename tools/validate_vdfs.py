#!/usr/bin/env python3
"""Validate VDF proofs across the blockchain using the pure-Rust VDF verifier.

Reads blocks from the blockchain SQLite DB, extracts VDF proofs, and verifies
them using chia_vdf_verify (pure Rust, no GMP/C++). The Rust code releases the
GIL, so verification runs in true parallel across threads.

Each block contains up to 5 VDF proofs (cc_sp, cc_ip, rc_sp, rc_ip, icc_ip).
Proofs with normalized_to_identity=True and all RC proofs use the identity
element as input and can be verified standalone. Non-normalized CC/ICC proofs
need chain state tracking and are skipped (~50% of proofs).

Usage:
    python tools/validate_vdfs.py                           # defaults
    python tools/validate_vdfs.py --db /path/to/db.sqlite   # custom DB
    python tools/validate_vdfs.py --start 1000 --end 2000   # height range
    python tools/validate_vdfs.py --workers 28              # parallelism
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import zstd
from chia_rs import FullBlock
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import validate_vdf

IDENTITY = ClassgroupElement.get_default_element()


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.verified = 0
        self.failed = 0
        self.skipped = 0
        self.total_blocks = 0
        self.last_height = 0
        self.first_failures: list[str] = []

    def record_ok(self) -> None:
        with self.lock:
            self.verified += 1

    def record_fail(self, height: int, label: str) -> None:
        with self.lock:
            self.failed += 1
            if len(self.first_failures) < 50:
                self.first_failures.append(f"height={height} {label}")

    def record_skip(self) -> None:
        with self.lock:
            self.skipped += 1

    def record_block(self, height: int) -> None:
        with self.lock:
            self.total_blocks += 1
            self.last_height = height

    def snapshot(self) -> tuple[int, int, int, int, int]:
        with self.lock:
            return (self.total_blocks, self.last_height, self.verified, self.failed, self.skipped)


def verify_one(height: int, label: str, proof: object, vdf_info: object, constants: object, stats: Stats) -> None:
    ok = validate_vdf(proof, constants, IDENTITY, vdf_info)
    if ok:
        stats.record_ok()
    else:
        stats.record_fail(height, label)


def main() -> None:
    default_db = str(Path.home() / ".chia/mainnet/db/blockchain_v2_mainnet.sqlite")

    parser = argparse.ArgumentParser(description="Validate VDF proofs using the pure-Rust verifier")
    parser.add_argument("--db", default=default_db, help="Path to blockchain_v2 SQLite DB")
    parser.add_argument("--start", type=int, default=0, help="Start height (default: 0)")
    parser.add_argument("--end", type=int, default=None, help="End height (default: all)")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 8, help="Thread pool size")
    args = parser.parse_args()

    print(f"DB: {args.db}")
    print(f"Range: {args.start} - {args.end or 'end'}")
    print(f"Workers: {args.workers}")
    print(f"Verifier: chia_vdf_verify (pure Rust, malachite bigints)")
    print()
    sys.stdout.flush()

    constants = DEFAULT_CONSTANTS
    stats = Stats()
    t0 = time.time()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.execute("pragma query_only = ON")
    query = "SELECT height, block FROM full_blocks WHERE in_main_chain = 1 AND height >= ?"
    params: list[int] = [args.start]
    if args.end is not None:
        query += " AND height <= ?"
        params.append(args.end)
    query += " ORDER BY height"

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        last_print = t0
        futures: list = []

        for row in conn.execute(query, params):
            height = row[0]
            block = FullBlock.from_bytes(zstd.decompress(row[1]))
            stats.record_block(height)
            rc = block.reward_chain_block

            proofs = []

            # Challenge chain signage point
            if block.challenge_chain_sp_proof is not None and rc.challenge_chain_sp_vdf is not None:
                p = block.challenge_chain_sp_proof
                if p.normalized_to_identity:
                    proofs.append(("cc_sp", p, rc.challenge_chain_sp_vdf))
                else:
                    stats.record_skip()

            # Challenge chain infusion point
            if block.challenge_chain_ip_proof is not None:
                p = block.challenge_chain_ip_proof
                if p.normalized_to_identity:
                    proofs.append(("cc_ip", p, rc.challenge_chain_ip_vdf))
                else:
                    stats.record_skip()

            # Reward chain signage point — always uses identity input
            if block.reward_chain_sp_proof is not None and rc.reward_chain_sp_vdf is not None:
                proofs.append(("rc_sp", block.reward_chain_sp_proof, rc.reward_chain_sp_vdf))

            # Reward chain infusion point — always uses identity input
            if block.reward_chain_ip_proof is not None:
                proofs.append(("rc_ip", block.reward_chain_ip_proof, rc.reward_chain_ip_vdf))

            # Infused challenge chain infusion point
            if block.infused_challenge_chain_ip_proof is not None and rc.infused_challenge_chain_ip_vdf is not None:
                p = block.infused_challenge_chain_ip_proof
                if p.normalized_to_identity:
                    proofs.append(("icc_ip", p, rc.infused_challenge_chain_ip_vdf))
                else:
                    stats.record_skip()

            for label, proof, vdf_info in proofs:
                fut = pool.submit(verify_one, height, label, proof, vdf_info, constants, stats)
                futures.append(fut)

            now = time.time()
            if now - last_print > 30:
                elapsed = now - t0
                blks, h, ok, fail, skip = stats.snapshot()
                rate = blks / elapsed if elapsed > 0 else 0
                remaining = max(0, (args.end or 8_400_000) - blks)
                eta_h = remaining / rate / 3600 if rate > 0 else 0
                print(
                    f"  height={h}  blocks={blks}  ok={ok}  fail={fail}  skip={skip}  "
                    f"rate={rate:.0f} blk/s  eta={eta_h:.1f}h  elapsed={elapsed:.0f}s"
                )
                sys.stdout.flush()
                last_print = now

            if len(futures) > 10000:
                for f in futures:
                    f.result()
                futures.clear()

        for f in futures:
            f.result()

    conn.close()

    elapsed = time.time() - t0
    blks, h, ok, fail, skip = stats.snapshot()
    rate = blks / elapsed if elapsed > 0 else 0
    print()
    print(f"Done: {blks} blocks (height {args.start} - {h})")
    print(f"  Verified: {ok} VDF proofs")
    print(f"  Failed:   {fail}")
    print(f"  Skipped:  {skip} (non-normalized, need chain state)")
    print(f"  Time:     {elapsed:.1f}s ({rate:.0f} blk/s)")

    if stats.first_failures:
        print()
        print("First failures:")
        for f in stats.first_failures:
            print(f"  {f}")
    else:
        print()
        print("ALL VERIFIED VDF PROOFS PASSED (pure Rust verifier)")

    sys.exit(1 if fail > 0 else 0)


if __name__ == "__main__":
    main()
