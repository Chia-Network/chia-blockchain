from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from click import BadParameter, Context

from chia.cmds.param_types import ADDRESS_TYPE, AMOUNT_TYPE, BYTES32_TYPE, TRANSACTION_FEE, CliAddress, CliAmount
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint64
from chia.wallet.util.address_type import AddressType

"""
This File tests all of the custom click param types.
Click automatically handles all cases where it is None and all cases where it is in some sort of Iterable.
"""

burn_ph = bytes32.from_hexstr("0x000000000000000000000000000000000000000000000000000000000000dead")
burn_address = encode_puzzle_hash(burn_ph, "xch")
burn_address_txch = encode_puzzle_hash(burn_ph, "txch")
burn_nft_addr = encode_puzzle_hash(burn_ph, "did:chia:")
burn_bad_prefix = encode_puzzle_hash(burn_ph, "badprefix")


class FakeContext:
    obj: dict[Any, Any] = {}

    def __init__(self, obj: dict[Any, Any]):
        self.obj = obj


def test_click_tx_fee_type() -> None:
    # Test uint64 (only used as default)
    assert TRANSACTION_FEE.convert(uint64(10000), None, None) == uint64(10000)

    # TODO: Test MOJO Logic When Implemented

    # Test Decimal / XCH
    assert TRANSACTION_FEE.convert("0.5", None, None) == uint64(int(0.5 * units["chia"]))
    assert TRANSACTION_FEE.convert("0", None, None) == uint64(0)
    # Test Decimal Failures
    with pytest.raises(BadParameter):
        TRANSACTION_FEE.convert("test", None, None)
    with pytest.raises(BadParameter):
        TRANSACTION_FEE.convert("0.6", None, None)
    with pytest.raises(BadParameter):
        TRANSACTION_FEE.convert("-0.6", None, None)


def test_click_amount_type() -> None:
    decimal_cli_amount = CliAmount(mojos=False, amount=Decimal(5.25))
    large_decimal_amount = CliAmount(mojos=False, amount=Decimal(10000000000))
    mojos_cli_amount = CliAmount(mojos=True, amount=uint64(100000))
    # Test CliAmount (Generally is not used)
    assert AMOUNT_TYPE.convert(decimal_cli_amount, None, None) == decimal_cli_amount

    # Test uint64 (only usable as default)
    assert AMOUNT_TYPE.convert(uint64(100000), None, None) == mojos_cli_amount

    # TODO: Test MOJO Logic When Implemented

    # Test Decimal / XCH (we dont test overflow because we dont know the conversion ratio yet)
    assert AMOUNT_TYPE.convert("5.25", None, None) == decimal_cli_amount
    assert AMOUNT_TYPE.convert("10000000000", None, None) == large_decimal_amount
    # Test Decimal Failures
    with pytest.raises(BadParameter):
        AMOUNT_TYPE.convert("test", None, None)
    with pytest.raises(BadParameter):
        AMOUNT_TYPE.convert("0", None, None)
    with pytest.raises(BadParameter):
        AMOUNT_TYPE.convert("-0.6", None, None)

    # Test CliAmount Class
    assert decimal_cli_amount.convert_amount(units["chia"]) == uint64(int(5.25 * units["chia"]))
    assert mojos_cli_amount.convert_amount(units["chia"]) == uint64(100000)
    with pytest.raises(ValueError):  # incorrect arg
        CliAmount(mojos=True, amount=Decimal(5.25)).convert_amount(units["chia"])
    with pytest.raises(ValueError):  # incorrect arg
        CliAmount(mojos=False, amount=uint64(100000)).convert_amount(units["chia"])
    with pytest.raises(ValueError):  # overflow
        large_decimal_amount.convert_amount(units["chia"])


def test_click_address_type() -> None:
    context = cast(Context, FakeContext(obj={"expected_prefix": "xch"}))  # this makes us not have to use a config file
    std_cli_address = CliAddress(burn_ph, burn_address, AddressType.XCH)
    nft_cli_address = CliAddress(burn_ph, burn_nft_addr, AddressType.DID)
    # Test CliAddress (Generally is not used)
    assert ADDRESS_TYPE.convert(std_cli_address, None, context) == std_cli_address

    # test address parsing
    assert ADDRESS_TYPE.convert(burn_address, None, context) == std_cli_address
    assert ADDRESS_TYPE.convert(burn_nft_addr, None, context) == nft_cli_address

    # check address type validation
    assert std_cli_address.validate_address_type(AddressType.XCH) == burn_address
    assert std_cli_address.validate_address_type_get_ph(AddressType.XCH) == burn_ph
    assert nft_cli_address.validate_address_type(AddressType.DID) == burn_nft_addr
    assert nft_cli_address.validate_address_type_get_ph(AddressType.DID) == burn_ph
    # check error handling
    with pytest.raises(BadParameter):
        ADDRESS_TYPE.convert("test", None, None)
    with pytest.raises(AttributeError):  # attribute error because the context does not have a real error handler
        ADDRESS_TYPE.convert(burn_address_txch, None, context)
    with pytest.raises(BadParameter):
        ADDRESS_TYPE.convert(burn_bad_prefix, None, None)

    # check class error handling
    with pytest.raises(ValueError):
        std_cli_address.validate_address_type_get_ph(AddressType.DID)
    with pytest.raises(ValueError):
        std_cli_address.validate_address_type(AddressType.DID)


def test_click_address_type_config(root_path_populated_with_config: Path) -> None:
    # set root path in context.
    context = cast(Context, FakeContext(obj={"root_path": root_path_populated_with_config}))
    # run test that should pass
    assert ADDRESS_TYPE.convert(burn_address, None, context) == CliAddress(burn_ph, burn_address, AddressType.XCH)
    assert context.obj["expected_prefix"] == "xch"  # validate that the prefix was set correctly
    # use txch address
    with pytest.raises(AttributeError):  # attribute error because the context does not have a real error handler
        ADDRESS_TYPE.convert(burn_address_txch, None, context)


def test_click_bytes32_type() -> None:
    # Test bytes32 (Generally it is not used)
    assert BYTES32_TYPE.convert(burn_ph, None, None) == burn_ph

    # test bytes32 parsing
    assert BYTES32_TYPE.convert("0x" + burn_ph.hex(), None, None) == burn_ph
    # check error handling
    with pytest.raises(BadParameter):
        BYTES32_TYPE.convert("test", None, None)
