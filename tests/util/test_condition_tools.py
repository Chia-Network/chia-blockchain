from __future__ import annotations

from typing import List, Tuple

import pytest
from blspy import G1Element
from clvm.casts import int_to_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.condition_tools import parse_sexp_to_conditions, pkm_pairs, pkm_pairs_for_conditions_dict
from chia.util.errors import ConsensusError
from chia.util.hash import std_hash

H1 = bytes32(b"a" * 32)
H2 = bytes32(b"b" * 32)
H3 = bytes32(b"c" * 32)

PK1 = G1Element.generator()
PK2 = G1Element.generator()

TEST_COIN = Coin(H1, H2, 123)


def mk_agg_sig_conditions(
    opcode: ConditionOpcode,
    agg_sig_data: List[Tuple[bytes, bytes]],
    agg_sig_unsafe_data: List[Tuple[bytes, bytes]] = [],
) -> SpendBundleConditions:
    spend = Spend(
        coin_id=TEST_COIN.name(),
        parent_id=H1,
        puzzle_hash=H2,
        coin_amount=123,
        height_relative=None,
        seconds_relative=None,
        before_height_relative=None,
        before_seconds_relative=None,
        birth_height=None,
        birth_seconds=None,
        create_coin=[],
        agg_sig_me=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_ME else [],
        agg_sig_amount=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_AMOUNT else [],
        agg_sig_parent=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_PARENT else [],
        agg_sig_parent_amount=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_PARENT_AMOUNT else [],
        agg_sig_parent_puzzle=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_PARENT_PUZZLE else [],
        agg_sig_puzzle=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_PUZZLE else [],
        agg_sig_puzzle_amount=agg_sig_data if opcode == ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT else [],
        flags=0,
    )
    return SpendBundleConditions([spend], 0, 0, 0, None, None, agg_sig_unsafe_data, 0, 0, 0)


@pytest.mark.parametrize(
    "opcode",
    [
        ConditionOpcode.AGG_SIG_PARENT,
        ConditionOpcode.AGG_SIG_PUZZLE,
        ConditionOpcode.AGG_SIG_AMOUNT,
        ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
        ConditionOpcode.AGG_SIG_ME,
    ],
)
def test_pkm_pairs_vs_for_conditions_dict(opcode: ConditionOpcode) -> None:
    conds = mk_agg_sig_conditions(opcode, agg_sig_data=[(bytes48(PK1), b"msg1"), (bytes48(PK2), b"msg2")])
    pks, msgs = pkm_pairs(conds, b"foobar")
    result_aligned = [(x, y) for x, y in zip(pks, msgs)]
    conditions_dict = {opcode: [ConditionWithArgs(opcode, [PK1, b"msg1"]), ConditionWithArgs(opcode, [PK2, b"msg2"])]}
    result2 = pkm_pairs_for_conditions_dict(conditions_dict, TEST_COIN, b"foobar")
    assert result_aligned == result2

    # missing message argument
    with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
        conditions_dict = {opcode: [ConditionWithArgs(opcode, [PK1])]}
        result2 = pkm_pairs_for_conditions_dict(conditions_dict, TEST_COIN, b"foobar")

    with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
        conditions_dict = {opcode: [ConditionWithArgs(opcode, [])]}
        result2 = pkm_pairs_for_conditions_dict(conditions_dict, TEST_COIN, b"foobar")

    # extra argument
    with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
        conditions_dict = {opcode: [ConditionWithArgs(opcode, [PK1, b"msg1", b"msg2"])]}
        result2 = pkm_pairs_for_conditions_dict(conditions_dict, TEST_COIN, b"foobar")

    # message too long
    with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
        conditions_dict = {opcode: [ConditionWithArgs(opcode, [PK1, b"m" * 1025])]}
        result2 = pkm_pairs_for_conditions_dict(conditions_dict, TEST_COIN, b"foobar")


class TestPkmPairs:
    def test_empty_list(self) -> None:
        conds = SpendBundleConditions([], 0, 0, 0, None, None, [], 0, 0, 0)
        pks, msgs = pkm_pairs(conds, b"foobar")
        assert pks == []
        assert msgs == []

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    def test_no_agg_sigs(self, opcode: ConditionOpcode) -> None:
        conds = mk_agg_sig_conditions(opcode, agg_sig_data=[])
        pks, msgs = pkm_pairs(conds, b"foobar")
        assert pks == []
        assert msgs == []

    @pytest.mark.parametrize(
        "opcode, value",
        [
            (ConditionOpcode.AGG_SIG_PARENT, H1),
            (ConditionOpcode.AGG_SIG_PUZZLE, H2),
            (ConditionOpcode.AGG_SIG_AMOUNT, int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, H2 + int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PARENT_AMOUNT, H1 + int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PARENT_PUZZLE, H1 + H2),
            (ConditionOpcode.AGG_SIG_ME, TEST_COIN.name()),
        ],
    )
    def test_agg_sig_conditions(self, opcode: ConditionOpcode, value: bytes) -> None:
        conds = mk_agg_sig_conditions(opcode, agg_sig_data=[(bytes48(PK1), b"msg1"), (bytes48(PK2), b"msg2")])
        addendum = b"foobar" if opcode == ConditionOpcode.AGG_SIG_ME else std_hash(b"foobar" + opcode)
        pks, msgs = pkm_pairs(conds, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(PK1), bytes(PK2)]
        assert msgs == [b"msg1" + value + addendum, b"msg2" + value + addendum]

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    def test_agg_sig_unsafe(self, opcode: ConditionOpcode) -> None:
        conds = mk_agg_sig_conditions(
            opcode, agg_sig_data=[], agg_sig_unsafe_data=[(bytes48(PK1), b"msg1"), (bytes48(PK2), b"msg2")]
        )
        pks, msgs = pkm_pairs(conds, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(PK1), bytes(PK2)]
        assert msgs == [b"msg1", b"msg2"]

    @pytest.mark.parametrize(
        "opcode, value",
        [
            (ConditionOpcode.AGG_SIG_PARENT, H1),
            (ConditionOpcode.AGG_SIG_PUZZLE, H2),
            (ConditionOpcode.AGG_SIG_AMOUNT, int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, H2 + int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PARENT_AMOUNT, H1 + int_to_bytes(123)),
            (ConditionOpcode.AGG_SIG_PARENT_PUZZLE, H1 + H2),
            (ConditionOpcode.AGG_SIG_ME, TEST_COIN.name()),
        ],
    )
    def test_agg_sig_mixed(self, opcode: ConditionOpcode, value: bytes) -> None:
        conds = mk_agg_sig_conditions(
            opcode, agg_sig_data=[(bytes48(PK1), b"msg1")], agg_sig_unsafe_data=[(bytes48(PK2), b"msg2")]
        )
        addendum = b"foobar" if opcode == ConditionOpcode.AGG_SIG_ME else std_hash(b"foobar" + opcode)
        pks, msgs = pkm_pairs(conds, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(PK2), bytes(PK1)]
        assert msgs == [b"msg2", b"msg1" + value + addendum]

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_ME,
        ],
    )
    def test_agg_sig_unsafe_restriction(self, opcode: ConditionOpcode) -> None:
        conds = mk_agg_sig_conditions(
            opcode, agg_sig_data=[], agg_sig_unsafe_data=[(bytes48(PK1), b"msg1"), (bytes48(PK2), b"msg2")]
        )
        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs(conds, b"msg1")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs(conds, b"sg1")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs(conds, b"msg2")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs(conds, b"g2")


class TestPkmPairsForConditionDict:
    def test_agg_sig_unsafe_restriction(self) -> None:
        ASU = ConditionOpcode.AGG_SIG_UNSAFE

        conds = {ASU: [ConditionWithArgs(ASU, [PK1, b"msg1"]), ConditionWithArgs(ASU, [PK2, b"msg2"])]}
        tuples = pkm_pairs_for_conditions_dict(conds, TEST_COIN, b"msg10")
        assert tuples == [(bytes48(PK1), b"msg1"), (bytes48(PK2), b"msg2")]

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs_for_conditions_dict(conds, TEST_COIN, b"msg1")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs_for_conditions_dict(conds, TEST_COIN, b"sg1")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs_for_conditions_dict(conds, TEST_COIN, b"msg2")

        with pytest.raises(ConsensusError, match="INVALID_CONDITION"):
            pkm_pairs_for_conditions_dict(conds, TEST_COIN, b"g2")


class TestParseSexpCondition:
    def test_basic(self) -> None:
        conds = parse_sexp_to_conditions(Program.to([[bytes([49]), b"foo", b"bar"]]))
        assert conds == [ConditionWithArgs(ConditionOpcode.AGG_SIG_UNSAFE, [b"foo", b"bar"])]

    def test_oversized_op(self) -> None:
        with pytest.raises(ConsensusError):
            parse_sexp_to_conditions(Program.to([[bytes([49, 49]), b"foo", b"bar"]]))

    def test_empty_op(self) -> None:
        with pytest.raises(ConsensusError):
            parse_sexp_to_conditions(Program.to([[b"", b"foo", b"bar"]]))

    def test_list_op(self) -> None:
        with pytest.raises(ConsensusError):
            parse_sexp_to_conditions(Program.to([[[bytes([49])], b"foo", b"bar"]]))

    def test_list_arg(self) -> None:
        conds = parse_sexp_to_conditions(Program.to([[bytes([49]), [b"foo", b"bar"]]]))
        assert conds == [ConditionWithArgs(ConditionOpcode.AGG_SIG_UNSAFE, [])]

    def test_list_arg_truncate(self) -> None:
        conds = parse_sexp_to_conditions(Program.to([[bytes([49]), b"baz", [b"foo", b"bar"]]]))
        assert conds == [ConditionWithArgs(ConditionOpcode.AGG_SIG_UNSAFE, [b"baz"])]

    def test_arg_limit(self) -> None:
        conds = parse_sexp_to_conditions(Program.to([[bytes([49]), b"1", b"2", b"3", b"4", b"5", b"6"]]))
        assert conds == [ConditionWithArgs(ConditionOpcode.AGG_SIG_UNSAFE, [b"1", b"2", b"3", b"4"])]
