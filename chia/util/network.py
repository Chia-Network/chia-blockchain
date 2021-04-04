from chia.server.outbound_message import NodeType


def is_localhost(peer_host: str):
    return peer_host == "127.0.0.1" or peer_host == "localhost" or peer_host == "::1" or peer_host == "0:0:0:0:0:0:0:1"


def class_for_type(type: NodeType):
    if type is NodeType.FULL_NODE:
        from chia.full_node.full_node_api import FullNodeAPI

        return FullNodeAPI
    elif type is NodeType.WALLET:
        from chia.wallet.wallet_node_api import WalletNodeAPI

        return WalletNodeAPI
    elif type is NodeType.INTRODUCER:
        from chia.introducer.introducer_api import IntroducerAPI

        return IntroducerAPI
    elif type is NodeType.TIMELORD:
        from chia.timelord.timelord_api import TimelordAPI

        return TimelordAPI
    elif type is NodeType.FARMER:
        from chia.farmer.farmer_api import FarmerAPI

        return FarmerAPI
    elif type is NodeType.HARVESTER:
        from chia.harvester.harvester_api import HarvesterAPI

        return HarvesterAPI
    raise ValueError("No class for type")
