from __future__ import annotations

from chia.protocols.outbound_message import NodeType

INBOUND_LIMIT_DEFAULTS: dict[NodeType, tuple[str, int]] = {
    NodeType.HARVESTER: ("max_inbound_harvester", 5),
    NodeType.FARMER: ("max_inbound_farmer", 10),
    NodeType.TIMELORD: ("max_inbound_timelord", 5),
    NodeType.INTRODUCER: ("max_inbound_introducer", 5),
    NodeType.WALLET: ("max_inbound_wallet", 20),
    NodeType.DATA_LAYER: ("max_inbound_data_layer", 5),
    NodeType.SOLVER: ("max_inbound_solver", 1),
}

_EXPECTED_TYPES = set(NodeType) - {NodeType.FULL_NODE}
assert set(INBOUND_LIMIT_DEFAULTS) == _EXPECTED_TYPES, (
    f"INBOUND_LIMIT_DEFAULTS is missing or has extra entries: "
    f"missing={_EXPECTED_TYPES - set(INBOUND_LIMIT_DEFAULTS)}, "
    f"extra={set(INBOUND_LIMIT_DEFAULTS) - _EXPECTED_TYPES}"
)
