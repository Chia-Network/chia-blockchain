from __future__ import annotations

import sys
from io import StringIO

from chia_rs import AugSchemeMPL, PrivateKey

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_conditions,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


def test_debug_messages() -> None:
    sender_sk = PrivateKey.from_bytes(bytes([1] * 32))
    sender_pk = sender_sk.get_g1()
    sender_puz = puzzle_for_pk(sender_pk)
    sender_coin = Coin(bytes32.zeros, sender_puz.get_tree_hash(), uint64(10000))
    receiver_sk = PrivateKey.from_bytes(bytes([2] * 32))
    receiver_pk = receiver_sk.get_g1()
    receiver_puz = puzzle_for_pk(receiver_pk)
    receiver_coin = Coin(bytes32.zeros, receiver_puz.get_tree_hash(), uint64(10000))
    sender_conditions = Program.to(
        [
            [ConditionOpcode.SEND_MESSAGE, 0b010010, b"puzhash", receiver_coin.puzzle_hash],
            [ConditionOpcode.SEND_MESSAGE, 0b111111, b"coin_id", receiver_coin.name()],
            [
                ConditionOpcode.SEND_MESSAGE,
                0b101101,
                b"parent_amount",
                receiver_coin.parent_coin_info,
                receiver_coin.amount,
            ],
            [ConditionOpcode.SEND_MESSAGE, 0b100101, b"missing_args", receiver_coin.parent_coin_info],
            [ConditionOpcode.SEND_MESSAGE, 0b100100, b"missing", receiver_coin.parent_coin_info],
            [ConditionOpcode.SEND_MESSAGE, 0b001101, b"wrong_args", receiver_coin.puzzle_hash, receiver_coin.amount],
        ]
    )
    receiver_conditions = Program.to(
        [
            [ConditionOpcode.RECEIVE_MESSAGE, 0b010010, b"puzhash", sender_coin.puzzle_hash],
            [ConditionOpcode.RECEIVE_MESSAGE, 0b111111, b"coin_id", sender_coin.name()],
            [
                ConditionOpcode.RECEIVE_MESSAGE,
                0b101101,
                b"parent_amount",
                sender_coin.parent_coin_info,
                sender_coin.amount,
            ],
            [ConditionOpcode.RECEIVE_MESSAGE, 0b101101, b"missing_args", sender_coin.parent_coin_info],
            [ConditionOpcode.RECEIVE_MESSAGE, 0b001001, b"missing", sender_coin.amount],
            [ConditionOpcode.RECEIVE_MESSAGE, 0b001101, b"wrong_args", sender_coin.amount],
        ]
    )
    sender_sol = solution_for_conditions(sender_conditions)
    sender_delegated_puzzle = puzzle_for_conditions(sender_conditions)
    sender_msg = sender_delegated_puzzle.get_tree_hash()
    sender_sig = AugSchemeMPL.sign(sender_sk, sender_msg)
    sender_sb = WalletSpendBundle([make_spend(sender_coin, sender_puz, sender_sol)], sender_sig)

    receiver_sol = solution_for_conditions(receiver_conditions)
    receiver_delegated_puzzle = puzzle_for_conditions(receiver_conditions)
    receiver_msg = receiver_delegated_puzzle.get_tree_hash()
    receiver_sig = AugSchemeMPL.sign(receiver_sk, receiver_msg)
    receiver_sb = WalletSpendBundle([make_spend(receiver_coin, receiver_puz, receiver_sol)], receiver_sig)

    sb = WalletSpendBundle.aggregate([sender_sb, receiver_sb])
    result = StringIO()
    sys.stdout = result
    debug_spend_bundle(sb)


def test_debug_spend_bundle() -> None:
    sk = PrivateKey.from_bytes(bytes([1] * 32))
    pk = sk.get_g1()
    msg = bytes(32)
    sig = AugSchemeMPL.sign(sk, msg)
    ACS = Program.to(15).curry(Program.to("hey").curry("now")).curry("brown", "cow")
    ACS_PH = ACS.get_tree_hash()
    coin: Coin = Coin(bytes32.zeros, ACS_PH, uint64(3))
    child_coin: Coin = Coin(coin.name(), ACS_PH, uint64(0))
    coin_bad_reveal: Coin = Coin(bytes32.zeros, bytes32.zeros, uint64(0))
    solution = Program.to(
        [
            [ConditionOpcode.AGG_SIG_UNSAFE, pk, msg],
            [ConditionOpcode.REMARK],
            [ConditionOpcode.CREATE_COIN, ACS_PH, 0],
            [ConditionOpcode.CREATE_COIN, bytes32.zeros, 1],
            [ConditionOpcode.CREATE_COIN, bytes32.zeros, 2, [b"memo", b"memo", b"memo"]],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, bytes32.zeros],
            [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(coin.name())],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, b"hey"],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, None],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, bytes32.zeros],
            [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, std_hash(coin.puzzle_hash)],
            [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, b"hey"],
            [ConditionOpcode.SEND_MESSAGE, 0x17, ACS, ACS_PH],
        ]
    )

    result = StringIO()
    sys.stdout = result

    debug_spend_bundle(
        WalletSpendBundle(
            [
                make_spend(
                    coin_bad_reveal,
                    ACS,
                    Program.to(None),
                ),
                make_spend(
                    coin,
                    ACS,
                    solution,
                ),
                make_spend(
                    child_coin,
                    ACS,
                    Program.to(None),
                ),
            ],
            sig,
        )
    )

    # spend = WalletSpendBundle([make_spend(coin, ACS, solution)], sig)
