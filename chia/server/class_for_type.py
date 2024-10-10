from __future__ import annotations

from typing import Any

from chia.server.outbound_message import NodeType


def class_for_type(
    type: NodeType,
) -> Any:
    from chia.farmer.farmer_api import FarmerAPI
    from chia.full_node.full_node_api import FullNodeAPI
    from chia.harvester.harvester_api import HarvesterAPI
    from chia.introducer.introducer_api import IntroducerAPI
    from chia.timelord.timelord_api import TimelordAPI
    from chia.wallet.wallet_node_api import WalletNodeAPI

    if type is NodeType.FULL_NODE:
        return FullNodeAPI
    elif type is NodeType.WALLET:
        return WalletNodeAPI
    elif type is NodeType.INTRODUCER:
        return IntroducerAPI
    elif type is NodeType.TIMELORD:
        return TimelordAPI
    elif type is NodeType.FARMER:
        return FarmerAPI
    elif type is NodeType.HARVESTER:
        return HarvesterAPI
    raise ValueError("No class for type")
