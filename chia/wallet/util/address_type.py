from enum import Enum, auto
from typing import Set

from chia.util.bech32m import bech32_decode
from chia.util.config import selected_network_address_prefix


class AddressType(Enum):
    # def _generate_next_value_(name, start, count, last_values):
    # if name == "DEFAULT":
    #     print("_generate_next_value called for DEFAULT")
    #     return selected_network_address_prefix()
    # return name

    # DEFAULT = auto()
    XCH = "xch"
    TXCH = "txch"
    NFT = "nft"
    DID = "did:chia:"

    @classmethod
    def default_prefix(cls):
        # Loads the config, so use where appropriate
        return cls(selected_network_address_prefix())

    def hrp(self):
        return self.value


def is_valid_address(address: str, allowed_types: Set["AddressType"] = {AddressType.DEFAULT}) -> bool:
    try:
        ensure_valid_address(address, allowed_types)
        return True
    except ValueError:
        return False


def ensure_valid_address(address: str, allowed_types: Set["AddressType"] = {AddressType.DEFAULT}) -> str:
    hrp, data = bech32_decode(address)
    if not data:
        raise ValueError(f"Invalid address: {address}")
    if AddressType(hrp) not in allowed_types:
        raise ValueError(
            f"Invalid address: {address}. "
            f"Valid addresses must contain one of the following prefixes: {[t.value for t in allowed_types]}"
        )
    return address
