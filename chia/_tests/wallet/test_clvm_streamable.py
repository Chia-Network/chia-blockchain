from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

import pytest

from chia.types.blockchain_format.program import Program
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.clvm_streamable import (
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
    assert program_serialize_clvm_streamable(instance) == Program.to(["1"])
    assert byte_serialize_clvm_streamable(instance).hex() == "ff3180"
    assert json_serialize_with_clvm_streamable(instance) == "ff3180"
    assert program_deserialize_clvm_streamable(Program.to(["1"]), BasicCLVMStreamable) == instance
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ff3180"), BasicCLVMStreamable) == instance
    assert json_deserialize_with_clvm_streamable("ff3180", BasicCLVMStreamable) == instance


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
    assert json_serialize_with_clvm_streamable(instance) == {"inside": "ff3180", "a": "1"}
    assert json_deserialize_with_clvm_streamable({"inside": "ff3180", "a": "1"}, OutsideStreamable) == instance
    assert OutsideStreamable.from_json_dict({"a": "1", "inside": {"a": "1"}}) == instance

    instance_clvm = OutsideCLVM(a="1", inside=BasicCLVMStreamable(a="1"))
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([["1"], "1"])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff3180ff3180"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff3180ff3180"
    assert program_deserialize_clvm_streamable(Program.to([["1"], "1"]), OutsideCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff3180ff3180"), OutsideCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff3180ff3180", OutsideCLVM) == instance_clvm


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
    assert json_serialize_with_clvm_streamable(instance) == {"optional": "ff3180", "list": ["ff3180"]}
    assert json_deserialize_with_clvm_streamable({"optional": "ff3180", "list": ["ff3180"]}, Compound) == instance
    assert Compound.from_json_dict({"optional": {"a": "1"}, "list": [{"a": "1"}]}) == instance

    # regular streamable + falsey values
    instance = Compound(optional=None, list=[])
    assert json_serialize_with_clvm_streamable(instance) == {"optional": None, "list": []}
    assert json_deserialize_with_clvm_streamable({"optional": None, "list": []}, Compound) == instance
    assert Compound.from_json_dict({"optional": None, "list": []}) == instance

    # clvm streamable + regular values
    instance_clvm = CompoundCLVM(optional=BasicCLVMStreamable(a="1"), list=[BasicCLVMStreamable(a="1")])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([[True, "1"], [["1"]]])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff01ff3180ffffff31808080"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff01ff3180ffffff31808080"
    assert program_deserialize_clvm_streamable(Program.to([[True, "1"], [["1"]]]), CompoundCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff01ff3180ffffff31808080"), CompoundCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff01ff3180ffffff31808080", CompoundCLVM) == instance_clvm

    # clvm streamable + falsey values
    instance_clvm = CompoundCLVM(optional=None, list=[])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([[0], []])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff8080ff8080"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff8080ff8080"
    assert program_deserialize_clvm_streamable(Program.to([[0, 0], []]), CompoundCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff8080ff8080"), CompoundCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff8080ff8080", CompoundCLVM) == instance_clvm

    with pytest.raises(ValueError, match="@clvm_streamable"):

        @clvm_streamable
        @dataclasses.dataclass(frozen=True)
        class DoesntWork(Streamable):
            tuples_are_not_supported: Tuple[str]
