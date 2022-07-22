from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Set, Type, TypeVar

from chia.util.bech32m import bech32_decode, convertbits
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

    def expected_decoded_length(self) -> int:
        # Current address types encode 32 bytes. If future address types vary in
        # their length, this will need to be updated.
        return 32

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
    hrp, b32data = bech32_decode(address)
    if not b32data or not hrp:
        raise ValueError(f"Invalid address: {address}")
    address_type = AddressType(hrp)
    decoded_data = convertbits(b32data, 5, 8, False)
    if len(decoded_data) != address_type.expected_decoded_length():
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected {address_type.expected_decoded_length()} bytes, got {len(decoded_data)}"
        )
    if address_type not in allowed_types:
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected an address with one of the following prefixes: {[t.value for t in allowed_types]}"
        )
    return address
