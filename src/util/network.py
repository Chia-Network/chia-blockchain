import secrets

from src.server.outbound_message import NodeType
from src.types.sized_bytes import bytes32


def create_node_id() -> bytes32:
    """Generates a transient random node_id."""
    return bytes32(secrets.token_bytes(32))


def class_for_type(type: NodeType):
    if type is NodeType.FULL_NODE:
        from src.full_node.full_node_api import FullNodeAPI

        return FullNodeAPI
    elif type is NodeType.WALLET:
        from src.wallet.wallet_node_api import WalletNodeAPI

        return WalletNodeAPI
    elif type is NodeType.INTRODUCER:
        from src.introducer.introducer_api import IntroducerAPI

        return IntroducerAPI
    elif type is NodeType.TIMELORD:
        from src.timelord.timelord_api import TimelordAPI

        return TimelordAPI
    elif type is NodeType.FARMER:
        from src.farmer.farmer_api import FarmerAPI

        return FarmerAPI
    elif type is NodeType.HARVESTER:
        from src.harvester.harvester_api import HarvesterAPI

        return HarvesterAPI
    raise ValueError("No class for type")
