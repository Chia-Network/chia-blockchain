from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Set

from chia.util.bech32m import bech32_decode, convertbits
from chia.util.config import selected_network_address_prefix


class AddressType(Enum):
    XCH = "xch"
    NFT = "nft"
    DID = "did:chia:"

    def hrp(self, config: Dict[str, Any]) -> str:
        if self == AddressType.XCH:
            # Special case to map XCH to the current network's address prefix
            return selected_network_address_prefix(config)
        return self.value

    def expected_decoded_length(self) -> int:
        # Current address types encode 32 bytes. If future address types vary in
        # their length, this will need to be updated.
        return 32


def is_valid_address(address: str, allowed_types: Set[AddressType], config: Dict[str, Any]) -> bool:
    try:
        ensure_valid_address(address, allowed_types=allowed_types, config=config)
        return True
    except ValueError:
        return False


def ensure_valid_address(address: str, *, allowed_types: Set[AddressType], config: Dict[str, Any]) -> str:
    hrp, b32data = bech32_decode(address)
    if not b32data or not hrp:
        raise ValueError(f"Invalid address: {address}")
    # Match by prefix (hrp) and return the corresponding address type
    address_type = next(
        (addr_type for (addr_type, addr_hrp) in ((a, a.hrp(config)) for a in allowed_types) if addr_hrp == hrp),
        None,
    )
    if address_type is None:
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected an address with one of the following prefixes: {[t.hrp(config) for t in allowed_types]}"
        )
    decoded_data = convertbits(b32data, 5, 8, False)
    if len(decoded_data) != address_type.expected_decoded_length():
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected {address_type.expected_decoded_length()} bytes, got {len(decoded_data)}"
        )
    return address
