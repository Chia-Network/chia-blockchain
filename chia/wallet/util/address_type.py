from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Set, Type, TypeVar

from chia.util.bech32m import bech32_decode
from chia.util.config import selected_network_address_prefix
from chia.util.default_root import DEFAULT_ROOT_PATH

_T_AddressType = TypeVar("_T_AddressType", bound="AddressType")


class AddressType(Enum):
    XCH = "xch"
    TXCH = "txch"
    NFT = "nft"
    DID = "did:chia:"

    def hrp(self) -> str:
        return self.value

    @classmethod
    def current_network_address_type(
        cls: Type[_T_AddressType],
        config: Optional[Dict[str, Any]] = None,
        root_path: Path = DEFAULT_ROOT_PATH,
    ) -> _T_AddressType:
        return cls(selected_network_address_prefix(config, root_path))


def is_valid_address(address: str, allowed_types: Set[AddressType]) -> bool:
    try:
        ensure_valid_address(address, allowed_types=allowed_types)
        return True
    except ValueError:
        return False


def ensure_valid_address(address: str, *, allowed_types: Set[AddressType]) -> str:
    hrp, data = bech32_decode(address)
    if not data:
        raise ValueError(f"Invalid address: {address}")
    if AddressType(hrp) not in allowed_types:
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected an address with one of the following prefixes: {[t.value for t in allowed_types]}"
        )
    return address
