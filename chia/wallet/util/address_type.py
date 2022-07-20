from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Set, Type, TypeVar

from chia.util.bech32m import bech32_decode
from chia.util.config import selected_network_address_prefix

_T_CurrentNetworkAddressPrefix = TypeVar("_T_CurrentNetworkAddressPrefix", bound="CurrentNetworkAddressPrefix")


# Singleton representing the current network address prefix. Can be updated in case the config changes.
# Since AddressType is an Enum, it's not possible to have a class attribute within AddressType that is
# mutable. To support the case where the selected network address prefix changes, we use this class
# to store that prefix.
class CurrentNetworkAddressPrefix:
    current: str = selected_network_address_prefix()

    @classmethod
    def update(cls: Type[_T_CurrentNetworkAddressPrefix], value: str) -> None:
        cls.current = value


class AddressType(Enum):
    XCH = "xch"
    TXCH = "txch"
    NFT = "nft"
    DID = "did:chia:"

    def hrp(self) -> str:
        return self.value

    # Update the selected network address prefix in the singleton.
    # This should be called if the config changes.
    @classmethod
    def update_current_network_address_prefix(cls, new_prefix: Optional[str] = None) -> None:
        CurrentNetworkAddressPrefix.update(new_prefix or selected_network_address_prefix())


# Manipulates kwargs if `allowed_types`` is not specified, setting it to a set consisting
# of the selected network address prefix (xch|txch)
def default_allowed_types_if_none(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if "allowed_types" not in kwargs:
            # Add the selected network address prefix (xch|txch) to the list of allowed prefixes
            kwargs["allowed_types"] = {AddressType(CurrentNetworkAddressPrefix.current)}
        return f(*args, **kwargs)

    return wrapper


@default_allowed_types_if_none  # sets allowed_types to xch|txch if not specified
def is_valid_address(address: str, allowed_types: Set["AddressType"]) -> bool:
    try:
        ensure_valid_address(address, allowed_types)
        return True
    except ValueError:
        return False


@default_allowed_types_if_none  # sets allowed_types to xch|txch if not specified
def ensure_valid_address(address: str, allowed_types: Set["AddressType"]) -> str:
    hrp, data = bech32_decode(address)
    if not data:
        raise ValueError(f"Invalid address: {address}")
    if AddressType(hrp) not in allowed_types:
        raise ValueError(
            f"Invalid address: {address}. "
            f"Expected an address with one of the following prefixes: {[t.value for t in allowed_types]}"
        )
    return address
