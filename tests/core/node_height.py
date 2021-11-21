def node_height_at_least(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        print(f" ==== node_height_at_least {node.full_node.blockchain.get_peak().height!r} >= {h!r}")
        return node.full_node.blockchain.get_peak().height >= h
    print(f" ==== node_height_at_least False (h == {h!r})")
    return False


def node_height_exactly(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height == h
    return False


def node_height_between(node, h1, h2):
    if node.full_node.blockchain.get_peak() is not None:
        height = node.full_node.blockchain.get_peak().height
        return h1 <= height <= h2
    return False
