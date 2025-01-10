from __future__ import annotations

from chia.full_node.full_node_api import FullNodeAPI
from chia.util.ints import uint32


def node_height_at_least(node: FullNodeAPI, h: uint32) -> bool:
    if node.full_node.blockchain.get_peak() is not None:
        peak = node.full_node.blockchain.get_peak()
        if peak is not None:
            return peak.height >= h
    return False


def node_height_exactly(node: FullNodeAPI, h: uint32) -> bool:
    if node.full_node.blockchain.get_peak() is not None:
        peak = node.full_node.blockchain.get_peak()
        if peak is not None:
            return peak.height == h
    return False


def node_height_between(node: FullNodeAPI, h1: uint32, h2: uint32) -> bool:
    if node.full_node.blockchain.get_peak() is not None:
        peak = node.full_node.blockchain.get_peak()
        if peak is not None:
            return h1 <= peak.height <= h2
    return False
