from __future__ import annotations

from chia.util.ints import uint32


def node_height_at_least(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height >= h
    return False


def node_height(node) -> uint32:
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height
    return uint32(0)  # small simplification to ignore difference between None and 0


def node_height_exactly(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height == h
    return False


def node_height_between(node, h1, h2):
    if node.full_node.blockchain.get_peak() is not None:
        height = node.full_node.blockchain.get_peak().height
        return h1 <= height <= h2
    return False
