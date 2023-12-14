from __future__ import annotations

from time import monotonic
from typing import List

from chia.full_node.subscriptions import PeerSubscriptions
from chia.types.blockchain_format.sized_bytes import bytes32


def generate_ids(amount: int) -> List[bytes32]:
    next = bytes32(b"\0" * 32)
    ids = []
    for _ in range(0, amount):
        ids.append(next)
        for i in range(0, 32):
            if next[i] != 255:
                next = bytes32(next[:i] + bytes([next[i] + 1]) + next[i + 1 :])
                break
            else:
                next = bytes32(next[:i] + bytes([0]) + next[i + 1 :])
    return ids


def run_subscriptions_benchmark() -> None:
    subs = PeerSubscriptions()

    peer_id = bytes32(b"\0" * 32)
    puzzle_hashes = generate_ids(1000000)
    coin_ids = generate_ids(1000000)

    start = monotonic()

    subs.add_ph_subscriptions(peer_id, puzzle_hashes, len(puzzle_hashes))
    subs.add_coin_subscriptions(peer_id, coin_ids, len(coin_ids) * 2)

    stop = monotonic()

    print(f"insert time: {stop - start:0.4f}s")

    start = monotonic()

    for _ in range(3):
        for ph in puzzle_hashes:
            subs.has_ph_subscription(ph)
            subs.peers_for_puzzle_hash(ph)

        for coin_id in coin_ids:
            subs.has_coin_subscription(coin_id)
            subs.peers_for_coin_id(ph)

    stop = monotonic()

    print(f"lookup time: {stop - start:0.4f}s")


if __name__ == "__main__":
    import logging

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.WARNING)
    run_subscriptions_benchmark()
