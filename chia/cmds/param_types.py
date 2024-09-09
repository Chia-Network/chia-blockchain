from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional, Union

import click

from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import bech32_decode, decode_puzzle_hash
from chia.util.config import load_config, selected_network_address_prefix
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint64
from chia.wallet.util.address_type import AddressType

one_decimal_mojo = Decimal("1e-12")


def validate_uint64(
    value: str,
    fail_func: Callable[[str, Optional[click.Parameter], Optional[click.Context]], None],
    param: Optional[click.Parameter],
    ctx: Optional[click.Context],
) -> uint64:
    try:
        d_value = Decimal(value)
    except InvalidOperation as e:
        fail_func(f"Value must be a valid number: {e}", param, ctx)
    if d_value.is_signed():
        fail_func("Value must be a positive integer", param, ctx)
    if d_value != d_value.to_integral():
        fail_func("Value must be an integer", param, ctx)
    try:
        u_value = uint64(value)
    except ValueError:
        fail_func("Value must be a valid uint64 number", param, ctx)
    return u_value


def validate_decimal_xch(
    value: str,
    fail_func: Callable[[str, Optional[click.Parameter], Optional[click.Context]], None],
    param: Optional[click.Parameter],
    ctx: Optional[click.Context],
) -> Decimal:
    try:
        d_value = Decimal(value)
    except InvalidOperation:
        fail_func("Value must be decimal dotted value in XCH (e.g. 0.00005)", param, ctx)
    if d_value.is_signed():
        fail_func("Value can not be negative", param, ctx)
    if d_value % one_decimal_mojo != Decimal(0):  # if there is a remainder, it contains a value smaller than one mojo
        fail_func("Invalid amount of mojos, Partial mojos (Fractions of a mojo).", param, ctx)
    return d_value


class TransactionFeeParamType(click.ParamType):
    """
    A Click parameter type for transaction fees, which can be specified in XCH or mojos.
    """

    name: str = "XCH"  # type name for cli, TODO: Change once the mojo flag is implemented
    value_limit: Decimal = Decimal("0.5")

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> uint64:
        # suggested by click, but we are not using it to avoid possible misinterpretation of units.
        # if isinstance(value, uint64):
        #     return value
        if not isinstance(value, str):
            self.fail("Invalid Type, fee must be string.", param, ctx)
        mojos = False  # TODO: Add unit logic
        if mojos:
            return validate_uint64(value, self.fail, param, ctx)
        d_value = validate_decimal_xch(value, self.fail, param, ctx)
        if not self.value_limit.is_zero() and d_value > self.value_limit:
            self.fail(f"Fee must be in the range 0 to {self.value_limit}", param, ctx)
        try:
            return uint64(d_value * units["chia"])
        except ValueError:
            self.fail("Fee must be a valid uint64 number", param, ctx)


@dataclass(frozen=True)
class CliAmount:
    """
    A dataclass for TX / wallet amounts for both XCH and CAT, and of course mojos.
    """

    mojos: bool
    amount: Union[uint64, Decimal, None]  # uint64 if mojos, Decimal if not, None if default value is none

    def convert_amount_with_default(
        self, mojo_per_unit: int, default_value: Optional[uint64] = uint64(0)
    ) -> Optional[uint64]:
        if self.amount is None:  # if the value is set to none, return the default value
            return default_value
        return self.convert_amount(mojo_per_unit)

    def convert_amount(self, mojo_per_unit: int) -> uint64:
        if self.mojos:
            if not isinstance(self.amount, uint64):
                raise ValueError("Amount must be a uint64 if mojos flag is set.")
            return self.amount
        if not isinstance(self.amount, Decimal):
            raise ValueError("Amount must be a Decimal if mojos flag is not set.")
        converted_amount = self.amount * mojo_per_unit
        uint64_amount = uint64(converted_amount)
        if uint64_amount != converted_amount:
            raise ValueError(
                "Too much decimal precision specified."
                "Please use the units of the balance numbers from `chia wallet show`"
            )
        return uint64_amount


class AmountParamType(click.ParamType):
    """
    A Click parameter type for TX / wallet amounts for both XCH and CAT, and of course mojos.
    """

    name: str = "XCH"  # type name for cli, TODO: Change once the mojo flag is implemented

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> CliAmount:
        # suggested by click, but being left in as mojos flag makes default misrepresentation less likely.
        if isinstance(value, CliAmount):
            return value
        if not isinstance(value, str):
            self.fail("Invalid Type, amount must be string or CliAmount.", param, ctx)
        mojos = False  # TODO: Add unit logic
        if mojos:
            m_value = validate_uint64(value, self.fail, param, ctx)
            return CliAmount(mojos=True, amount=m_value)
        d_value = validate_decimal_xch(value, self.fail, param, ctx)
        return CliAmount(mojos=False, amount=d_value)


@dataclass(frozen=True)
class CliAddress:
    """
    A dataclass for the cli, with the address type and puzzle hash.
    """

    puzzle_hash: bytes32
    original_address: str
    address_type: AddressType

    def validate_address_type(self, address_type: AddressType) -> str:
        if self.address_type is not address_type:
            raise ValueError(f"Address must be of type {address_type}")
        return self.original_address

    def validate_address_type_get_ph(self, address_type: AddressType) -> bytes32:
        if self.address_type is not address_type:
            raise ValueError(f"Address must be of type {address_type}")
        return self.puzzle_hash


class AddressParamType(click.ParamType):
    """
    A Click parameter type for bech32m encoded addresses, it gives a class with the address type and puzzle hash.
    """

    name: str = "Address"  # type name for cli

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> CliAddress:
        # suggested by click, but not really used so removed to make unexpected types more obvious.
        # if isinstance(value, CliAddress):
        #    return value
        if not isinstance(value, str):
            self.fail("Invalid Type, address must be string.", param, ctx)
        try:
            hrp, b32data = bech32_decode(value)
            if hrp in ["xch", "txch"]:  # I hate having to load the config here
                addr_type: AddressType = AddressType.XCH
                expected_prefix = ctx.obj.get("expected_prefix") if ctx else None  # attempt to get cached prefix
                if expected_prefix is None:
                    root_path = ctx.obj["root_path"] if ctx is not None else DEFAULT_ROOT_PATH
                    config = load_config(root_path, "config.yaml")
                    expected_prefix = selected_network_address_prefix(config)

                    if ctx is not None:
                        ctx.obj["expected_prefix"] = expected_prefix  # cache prefix
                # now that we have the expected prefix, we can validate the address is for the right network
                if hrp != expected_prefix:
                    self.fail(f"Unexpected Address Prefix: {hrp}, are you sure its for the right network?", param, ctx)
            else:  # all other address prefixes (Not xch / txch)
                addr_type = AddressType(hrp)
            return CliAddress(puzzle_hash=decode_puzzle_hash(value), address_type=addr_type, original_address=value)
        except ValueError:
            self.fail("Address must be a valid bech32m address", param, ctx)


class Bytes32ParamType(click.ParamType):
    """
    A Click parameter type for bytes32 hex strings, with or without the 0x prefix.
    """

    name: str = "HexString"  # type name for cli

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> bytes32:
        # suggested by click but deemed not necessary due to unnecessary complexity.
        # if isinstance(value, bytes32):
        #     return value
        if not isinstance(value, str):
            self.fail("Invalid Type, value must be string.", param, ctx)
        try:
            return bytes32.from_hexstr(value)
        except ValueError:
            self.fail("Value must be a valid bytes32 hex string like a coin id or puzzle hash", param, ctx)


class Uint64ParamType(click.ParamType):
    """
    A Click parameter type for Uint64 integers.
    """

    name: str = uint64.__name__  # type name for cli

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> uint64:
        if isinstance(value, uint64):  # required by click
            return value
        if not isinstance(value, str):
            self.fail("Invalid Type, value must be string or uint64.", param, ctx)
        return validate_uint64(value, self.fail, param, ctx)


cli_amount_none = CliAmount(mojos=False, amount=None)
