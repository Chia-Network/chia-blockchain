from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.signer_protocol import Coin, Spend
from chia.wallet.util.clvm_streamable import (
    TranslationLayer,
    TranslationLayerMapping,
    byte_deserialize_clvm_streamable,
    byte_serialize_clvm_streamable,
    clvm_streamable,
    json_deserialize_with_clvm_streamable,
    json_serialize_with_clvm_streamable,
    program_deserialize_clvm_streamable,
    program_serialize_clvm_streamable,
)


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class BasicCLVMStreamable(Streamable):
    a: str


def test_basic_serialization() -> None:
    instance = BasicCLVMStreamable(a="1")
    assert program_serialize_clvm_streamable(instance) == Program.to([("a", "1")])
    assert byte_serialize_clvm_streamable(instance).hex() == "ffff613180"
    assert json_serialize_with_clvm_streamable(instance) == "ffff613180"
    assert program_deserialize_clvm_streamable(Program.to([("a", "1")]), BasicCLVMStreamable) == instance
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff613180"), BasicCLVMStreamable) == instance
    assert json_deserialize_with_clvm_streamable("ffff613180", BasicCLVMStreamable) == instance


@streamable
@dataclasses.dataclass(frozen=True)
class OutsideStreamable(Streamable):
    inside: BasicCLVMStreamable
    a: str


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class OutsideCLVM(Streamable):
    inside: BasicCLVMStreamable
    a: str


def test_nested_serialization() -> None:
    instance = OutsideStreamable(a="1", inside=BasicCLVMStreamable(a="1"))
    assert json_serialize_with_clvm_streamable(instance) == {"inside": "ffff613180", "a": "1"}
    assert json_deserialize_with_clvm_streamable({"inside": "ffff613180", "a": "1"}, OutsideStreamable) == instance
    assert OutsideStreamable.from_json_dict({"a": "1", "inside": {"a": "1"}}) == instance

    instance_clvm = OutsideCLVM(a="1", inside=BasicCLVMStreamable(a="1"))
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([["inside", ("a", "1")], ("a", "1")])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff86696e73696465ffff613180ffff613180"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff86696e73696465ffff613180ffff613180"
    assert (
        program_deserialize_clvm_streamable(Program.to([["inside", ("a", "1")], ("a", "1")]), OutsideCLVM)
        == instance_clvm
    )
    assert (
        byte_deserialize_clvm_streamable(bytes.fromhex("ffff86696e73696465ffff613180ffff613180"), OutsideCLVM)
        == instance_clvm
    )
    assert json_deserialize_with_clvm_streamable("ffff86696e73696465ffff613180ffff613180", OutsideCLVM) == instance_clvm


@streamable
@dataclasses.dataclass(frozen=True)
class Compound(Streamable):
    optional: Optional[BasicCLVMStreamable]
    list: List[BasicCLVMStreamable]


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class CompoundCLVM(Streamable):
    optional: Optional[BasicCLVMStreamable]
    list: List[BasicCLVMStreamable]


def test_compound_type_serialization() -> None:
    # regular streamable + regular values
    instance = Compound(optional=BasicCLVMStreamable(a="1"), list=[BasicCLVMStreamable(a="1")])
    assert json_serialize_with_clvm_streamable(instance) == {"optional": "ffff613180", "list": ["ffff613180"]}
    assert (
        json_deserialize_with_clvm_streamable({"optional": "ffff613180", "list": ["ffff613180"]}, Compound) == instance
    )
    assert Compound.from_json_dict({"optional": {"a": "1"}, "list": [{"a": "1"}]}) == instance

    # regular streamable + falsey values
    instance = Compound(optional=None, list=[])
    assert json_serialize_with_clvm_streamable(instance) == {"optional": None, "list": []}
    assert json_deserialize_with_clvm_streamable({"optional": None, "list": []}, Compound) == instance
    assert Compound.from_json_dict({"optional": None, "list": []}) == instance

    # clvm streamable + regular values
    instance_clvm = CompoundCLVM(optional=BasicCLVMStreamable(a="1"), list=[BasicCLVMStreamable(a="1")])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to(
        [["optional", 1, (97, 49)], ["list", [(97, 49)]]]
    )
    assert (
        byte_serialize_clvm_streamable(instance_clvm).hex()
        == "ffff886f7074696f6e616cff01ffff613180ffff846c697374ffffff6131808080"
    )
    assert (
        json_serialize_with_clvm_streamable(instance_clvm)
        == "ffff886f7074696f6e616cff01ffff613180ffff846c697374ffffff6131808080"
    )
    assert (
        program_deserialize_clvm_streamable(Program.to([["optional", 1, (97, 49)], ["list", [(97, 49)]]]), CompoundCLVM)
        == instance_clvm
    )
    assert (
        byte_deserialize_clvm_streamable(
            bytes.fromhex("ffff886f7074696f6e616cff01ffff613180ffff846c697374ffffff6131808080"), CompoundCLVM
        )
        == instance_clvm
    )
    assert (
        json_deserialize_with_clvm_streamable(
            "ffff886f7074696f6e616cff01ffff613180ffff846c697374ffffff6131808080", CompoundCLVM
        )
        == instance_clvm
    )

    # clvm streamable + falsey values
    instance_clvm = CompoundCLVM(optional=None, list=[])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([["optional", 0], ["list"]])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff886f7074696f6e616cff8080ffff846c6973748080"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff886f7074696f6e616cff8080ffff846c6973748080"
    assert program_deserialize_clvm_streamable(Program.to([["optional", 0], ["list"]]), CompoundCLVM) == instance_clvm
    assert (
        byte_deserialize_clvm_streamable(bytes.fromhex("ffff886f7074696f6e616cff8080ffff846c6973748080"), CompoundCLVM)
        == instance_clvm
    )
    assert (
        json_deserialize_with_clvm_streamable("ffff886f7074696f6e616cff8080ffff846c6973748080", CompoundCLVM)
        == instance_clvm
    )

    with pytest.raises(ValueError, match="@clvm_streamable"):

        @clvm_streamable
        @dataclasses.dataclass(frozen=True)
        class DoesntWork(Streamable):
            tuples_are_not_supported: Tuple[str]


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class FooSpend(Streamable):
    coin: Coin
    puzzle_and_solution: Program

    @staticmethod
    def from_wallet_api(_from: Spend) -> FooSpend:
        return FooSpend(
            _from.coin,
            Program.to((_from.puzzle, _from.solution)),
        )

    @staticmethod
    def to_wallet_api(_from: FooSpend) -> Spend:
        return Spend(
            _from.coin,
            _from.puzzle_and_solution.first(),
            _from.puzzle_and_solution.rest(),
        )


def test_translation_layer() -> None:
    FOO_TRANSLATION = TranslationLayer(
        [
            TranslationLayerMapping(
                Spend,
                FooSpend,
                FooSpend.from_wallet_api,
                FooSpend.to_wallet_api,
            )
        ]
    )

    coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    spend = Spend(
        coin,
        Program.to("puzzle"),
        Program.to("solution"),
    )
    foo_spend = FooSpend(
        coin,
        Program.to(("puzzle", "solution")),
    )

    byte_serialize_clvm_streamable(foo_spend) == byte_serialize_clvm_streamable(
        spend, translation_layer=FOO_TRANSLATION
    )
    program_serialize_clvm_streamable(foo_spend) == program_serialize_clvm_streamable(
        spend, translation_layer=FOO_TRANSLATION
    )
    json_serialize_with_clvm_streamable(foo_spend) == json_serialize_with_clvm_streamable(
        spend, translation_layer=FOO_TRANSLATION
    )
    assert spend == byte_deserialize_clvm_streamable(
        byte_serialize_clvm_streamable(foo_spend), Spend, translation_layer=FOO_TRANSLATION
    )
    assert spend == program_deserialize_clvm_streamable(
        program_serialize_clvm_streamable(foo_spend), Spend, translation_layer=FOO_TRANSLATION
    )
    assert spend == json_deserialize_with_clvm_streamable(
        json_serialize_with_clvm_streamable(foo_spend), Spend, translation_layer=FOO_TRANSLATION
    )

    # Deserialization should only work now if using the translation layer
    with pytest.raises(Exception):
        byte_deserialize_clvm_streamable(byte_serialize_clvm_streamable(foo_spend), Spend)
    with pytest.raises(Exception):
        program_deserialize_clvm_streamable(program_serialize_clvm_streamable(foo_spend), Spend)
    with pytest.raises(Exception):
        json_deserialize_with_clvm_streamable(json_serialize_with_clvm_streamable(foo_spend), Spend)

    # Test that types not registered with translation layer are serialized properly
    assert coin == byte_deserialize_clvm_streamable(
        byte_serialize_clvm_streamable(coin, translation_layer=FOO_TRANSLATION), Coin, translation_layer=FOO_TRANSLATION
    )
    assert coin == program_deserialize_clvm_streamable(
        program_serialize_clvm_streamable(coin, translation_layer=FOO_TRANSLATION),
        Coin,
        translation_layer=FOO_TRANSLATION,
    )
    assert coin == json_deserialize_with_clvm_streamable(
        json_serialize_with_clvm_streamable(coin, translation_layer=FOO_TRANSLATION),
        Coin,
        translation_layer=FOO_TRANSLATION,
    )
